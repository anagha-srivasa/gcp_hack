from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pymongo
from pymongo.collection import Collection
from pymongo.errors import ConfigurationError, ConnectionFailure, PyMongoError
import yaml


# --- Exceptions -----------------------------------------------------------------

class RepoConfigError(Exception):
	"""Raised when repository configuration is invalid or cannot be loaded."""


class DBConnectionError(Exception):
	"""Raised when the database connection fails or cannot be validated."""


class RepoOperationError(Exception):
	"""Raised for failures during CRUD or index operations."""


# --- Repository -----------------------------------------------------------------

class MongoDBRepo:
	"""
	MongoDB repository with robust logging and error handling.

	- Loads URI from properties.yml (supports keys: mongodb_uri or mongodb_pass) or env MONGODB_URI
	- Validates connection with a ping
	- Provides simple CRUD and index helpers
	"""

	def __init__(
		self,
		config_path: Optional[str] = None,
		db_name: str = "genai_hack_db",
		logger: Optional[logging.Logger] = None,
	) -> None:
		# If not provided, resolve to src/properties.yml relative to this file
		if config_path is None:
			here = os.path.dirname(os.path.abspath(__file__))
			# .../src/main/repo -> .../src
			self.config_path = os.path.normpath(os.path.join(here, "..", "..", "properties.yml"))
		else:
			self.config_path = config_path
		self.db_name = db_name
		self.logger = logger or self._init_logger()
		self.client = self._connect()
		self.db = self.client[self.db_name]

	# --- Setup ------------------------------------------------------------------

	def _init_logger(self) -> logging.Logger:
		logger = logging.getLogger(__name__)
		if not logger.handlers:
			handler = logging.StreamHandler()
			fmt = logging.Formatter(
				fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
				datefmt="%Y-%m-%d %H:%M:%S",
			)
			handler.setFormatter(fmt)
			logger.addHandler(handler)
			logger.setLevel(logging.INFO)
		return logger

	def _load_uri_from_config(self) -> str:
		# Prefer env var, then YAML, support both `:` or legacy `=` style.
		env_uri = os.getenv("MONGODB_URI")
		if env_uri:
			return env_uri

		if not os.path.exists(self.config_path):
			raise RepoConfigError(
				f"Config file not found at {self.config_path}. Set MONGODB_URI env var or provide a valid path."
			)

		try:
			with open(self.config_path, "r", encoding="utf-8") as f:
				raw = f.read()
		except OSError as e:
			raise RepoConfigError(f"Failed to read config file: {e}") from e

		# Try proper YAML first
		config: Optional[Mapping[str, Any]] = None
		try:
			parsed = yaml.safe_load(raw)
			if isinstance(parsed, Mapping):
				config = parsed
		except Exception as e:
			# Fall back to ad-hoc parsing of 'key = value' format
			self.logger.debug(f"YAML parse failed, falling back: {e}")

		if config is None:
			cfg: Dict[str, str] = {}
			for line in raw.splitlines():
				line = line.strip()
				if not line or line.startswith("#"):
					continue
				if "=" in line:
					k, v = line.split("=", 1)
					cfg[k.strip()] = v.strip().strip('"\'')
			config = cfg

		# Accept either key name
		uri = (
			str(config.get("mongodb_uri"))
			if config.get("mongodb_uri") is not None
			else str(config.get("mongodb_pass", ""))
		)
		if not uri or uri.lower().startswith("none"):
			raise RepoConfigError(
				"MongoDB URI not found in config. Use key 'mongodb_uri' or 'mongodb_pass', or set MONGODB_URI env var."
			)
		return uri

	def _connect(self) -> pymongo.MongoClient:
		uri = self._load_uri_from_config()
		try:
			client = pymongo.MongoClient(
				uri,
				serverSelectionTimeoutMS=5000,
				socketTimeoutMS=10000,
				connectTimeoutMS=5000,
				retryWrites=True,
				appname="genai_hack",
			)
			# Validate connectivity
			client.admin.command("ping")
			self.logger.info("MongoDB connection validated via ping.")
			return client
		except (ConfigurationError, ConnectionFailure, PyMongoError) as e:
			self.logger.error(f"Failed to connect or ping MongoDB: {e}")
			raise DBConnectionError(str(e)) from e

	def _collection(self, collection_name: str) -> Collection:
		if not collection_name or not isinstance(collection_name, str):
			raise RepoOperationError("collection_name must be a non-empty string")
		return self.db[collection_name]

	# --- Indexes ----------------------------------------------------------------

	def create_index(
		self,
		collection_name: str,
		index_fields: Sequence[Union[str, Tuple[str, int]]],
		unique: bool = False,
		sparse: bool = False,
		name: Optional[str] = None,
	) -> str:
		"""Create an index. index_fields can be ["field1", ("field2", pymongo.DESCENDING)]."""
		try:
			keys: List[Tuple[str, int]] = []
			for f in index_fields:
				if isinstance(f, str):
					keys.append((f, pymongo.ASCENDING))
				else:
					fname, order = f
					if order not in (pymongo.ASCENDING, pymongo.DESCENDING, pymongo.TEXT):
						raise RepoOperationError(
							"order must be pymongo.ASCENDING, DESCENDING, or TEXT"
						)
					keys.append((fname, order))
			idx_name = self._collection(collection_name).create_index(
				keys, unique=unique, sparse=sparse, name=name
			)
			self.logger.info(
				f"Created index '{idx_name}' on {collection_name}: {keys}, unique={unique}, sparse={sparse}"
			)
			return idx_name
		except PyMongoError as e:
			self.logger.error(f"create_index failed on {collection_name}: {e}")
			raise RepoOperationError(str(e)) from e

	# --- CRUD -------------------------------------------------------------------

	def store(
		self, collection_name: str, data: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]
	) -> Union[Any, List[Any]]:
		"""Insert one document or many (if a sequence is provided). Returns inserted id(s)."""
		try:
			coll = self._collection(collection_name)
			if isinstance(data, Mapping):
				result = coll.insert_one(dict(data))
				self.logger.info(
					f"Inserted 1 document into {collection_name} with _id={result.inserted_id}"
				)
				return result.inserted_id
			elif isinstance(data, Sequence):
				docs = [dict(d) for d in data]  # shallow copy for safety
				if not docs:
					raise RepoOperationError("store called with empty sequence")
				result = coll.insert_many(docs)
				self.logger.info(
					f"Inserted {len(result.inserted_ids)} documents into {collection_name}"
				)
				return list(result.inserted_ids)
			else:
				raise RepoOperationError("data must be a mapping or a sequence of mappings")
		except PyMongoError as e:
			self.logger.error(f"store failed on {collection_name}: {e}")
			raise RepoOperationError(str(e)) from e

	def search(
		self,
		collection_name: str,
		query: Optional[Mapping[str, Any]] = None,
		projection: Optional[Mapping[str, int]] = None,
		limit: Optional[int] = None,
		sort: Optional[List[Tuple[str, int]]] = None,
	) -> List[Dict[str, Any]]:
		"""Find many documents matching query with optional projection/limit/sort."""
		try:
			coll = self._collection(collection_name)
			cursor = coll.find(query or {}, projection)
			if sort:
				cursor = cursor.sort(sort)
			if limit and limit > 0:
				cursor = cursor.limit(limit)
			results = list(cursor)
			self.logger.info(
				f"search on {collection_name} matched {len(results)} documents"
			)
			return results
		except PyMongoError as e:
			self.logger.error(f"search failed on {collection_name}: {e}")
			raise RepoOperationError(str(e)) from e

	def retrieve(
		self,
		collection_name: str,
		query: Mapping[str, Any],
		projection: Optional[Mapping[str, int]] = None,
	) -> Optional[Dict[str, Any]]:
		"""Find one document matching query."""
		try:
			coll = self._collection(collection_name)
			doc = coll.find_one(query, projection)
			self.logger.info(
				f"retrieve on {collection_name} returned {'1 document' if doc else 'no document'}"
			)
			return doc
		except PyMongoError as e:
			self.logger.error(f"retrieve failed on {collection_name}: {e}")
			raise RepoOperationError(str(e)) from e

	def delete(self, collection_name: str, query: Mapping[str, Any]) -> int:
		"""Delete documents matching query. Returns deleted count."""
		try:
			coll = self._collection(collection_name)
			result = coll.delete_many(query)
			self.logger.info(
				f"delete on {collection_name} removed {result.deleted_count} documents"
			)
			return int(result.deleted_count)
		except PyMongoError as e:
			self.logger.error(f"delete failed on {collection_name}: {e}")
			raise RepoOperationError(str(e)) from e

	# --- Utilities --------------------------------------------------------------

	def close(self) -> None:
		try:
			self.client.close()
			self.logger.info("MongoDB client closed.")
		except Exception as e:
			# Non-fatal; log at warning level
			self.logger.warning(f"Error while closing MongoDB client: {e}")

	def __enter__(self) -> "MongoDBRepo":
		return self

	def __exit__(self, exc_type, exc, tb) -> None:
		self.close()

# Example usage:
# with MongoDBRepo(config_path="../properties.yml") as repo:
#     repo.create_index("document_index", ["document_id"], unique=True)
#     repo.store("document_index", {"document_id": "doc_001", "title": "..."})
#     repo.search("document_index", {"author": "John Doe"}, limit=5)
#     repo.retrieve("document_index", {"document_id": "doc_001"})
#     repo.delete("document_index", {"document_id": "doc_001"})