import json
import logging
import os
import redis
from typing import Dict, Optional, List, Any
import time

logger = logging.getLogger(__name__)

class CacheManager:
    """Gestionnaire de cache avec Redis et persistance JSON."""
    
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        """Initialiser le gestionnaire de cache."""
        self.redis_client = None
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.connected = False
        self.json_file = 'faces_data.json'
        
        # Configuration des index Redis
        self.hash_prefix = "hash:"
        self.name_prefix = "name:"
        self.index_prefix = "index:"
        
        # Pipeline Redis pour les opérations en lot
        self.pipeline = None
        
        # Chargement initial des données
        self._load_from_json()
        
        # Création des index
        self._create_indexes()
        
        self._connect()

    def _connect(self) -> None:
        """Établir la connexion à Redis."""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_timeout=1  # Timeout court pour éviter les blocages
            )
            # Tester la connexion
            self.redis_client.ping()
            self.connected = True
            
            # Configuration du pipeline
            self.pipeline = self.redis_client.pipeline()
        except redis.ConnectionError:
            self.connected = False
            logger.warning("Impossible de se connecter à Redis. L'application fonctionnera en mode hors ligne.")
        except Exception as e:
            self.connected = False
            logger.warning(f"Erreur lors de la connexion à Redis: {e}. L'application fonctionnera en mode hors ligne.")

    def _ensure_connection(self) -> bool:
        """Vérifier et rétablir la connexion si nécessaire."""
        if not self.connected:
            self._connect()
        return self.connected

    def _create_indexes(self) -> None:
        """Crée les index Redis pour optimiser les recherches."""
        try:
            # Création d'un index sur les noms pour les recherches rapides
            all_data = self.get_all()
            for hash_val, name in all_data.items():
                # Index par hash
                self.redis_client.set(f"{self.hash_prefix}{hash_val}", name)
                # Index par nom (pour les recherches inverses)
                self.redis_client.sadd(f"{self.name_prefix}{name}", hash_val)
                # Index par première lettre du nom (pour les recherches partielles)
                first_letter = name[0].lower() if name else ''
                self.redis_client.sadd(f"{self.index_prefix}letter:{first_letter}", name)
            
            logger.info("Index Redis créés avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de la création des index Redis: {e}")

    def _load_from_json(self) -> None:
        """Charge les données du fichier JSON dans Redis avec pipeline."""
        try:
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not self._ensure_connection():
                        return
                        
                    # Utilisation du pipeline pour les opérations en lot
                    with self.redis_client.pipeline() as pipe:
                        for hash_val, name in data.items():
                            # Stockage principal
                            pipe.set(f"{self.hash_prefix}{hash_val}", name)
                            # Index par nom
                            pipe.sadd(f"{self.name_prefix}{name}", hash_val)
                            # Index par première lettre
                            first_letter = name[0].lower() if name else ''
                            pipe.sadd(f"{self.index_prefix}letter:{first_letter}", name)
                        pipe.execute()
                logger.info(f"Données chargées depuis {self.json_file} dans Redis")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des données depuis {self.json_file}: {e}")

    def get(self, image_hash: str) -> Optional[str]:
        """
        Récupère le nom associé à un hash d'image depuis le cache Redis.
        
        Args:
            image_hash (str): Hash de l'image
            
        Returns:
            Optional[str]: Nom associé au hash ou None si non trouvé
        """
        if not self._ensure_connection():
            return None
            
        try:
            return self.redis_client.get(f"{self.hash_prefix}{image_hash}")
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération depuis Redis: {e}")
            return None

    def set(self, image_hash: str, name: str) -> bool:
        """
        Stocke une association hash-nom dans Redis et met à jour le fichier JSON.
        
        Args:
            image_hash (str): Hash de l'image
            name (str): Nom associé au hash
        """
        if not self._ensure_connection():
            return False
            
        try:
            # Utilisation du pipeline pour les opérations en lot
            with self.redis_client.pipeline() as pipe:
                # Stockage principal
                pipe.set(f"{self.hash_prefix}{image_hash}", name)
                # Index par nom
                pipe.sadd(f"{self.name_prefix}{name}", image_hash)
                # Index par première lettre
                first_letter = name[0].lower() if name else ''
                pipe.sadd(f"{self.index_prefix}letter:{first_letter}", name)
                pipe.execute()
            
            # Mise à jour du fichier JSON
            self._update_json_file(image_hash, name)
            
            logger.info(f"Nouvelle association ajoutée: {image_hash} -> {name}")
            return True
        except Exception as e:
            logger.warning(f"Erreur lors de l'ajout de l'association: {e}")
            return False

    def _update_json_file(self, image_hash: str, name: str) -> None:
        """
        Met à jour le fichier JSON avec une nouvelle association hash-nom.
        
        Args:
            image_hash (str): Hash de l'image
            name (str): Nom associé au hash
        """
        try:
            # Charger les données existantes
            data = {}
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            # Mettre à jour les données
            data[image_hash] = name
            
            # Sauvegarder les données mises à jour
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du fichier JSON: {e}")

    def get_all(self) -> Dict[str, str]:
        """
        Récupère toutes les associations hash-nom depuis Redis.
        
        Returns:
            Dict[str, str]: Dictionnaire des associations hash-nom
        """
        if not self._ensure_connection():
            return {}
            
        try:
            # Utilisation de scan_iter pour une récupération efficace
            result = {}
            for key in self.redis_client.scan_iter(match=f"{self.hash_prefix}*"):
                value = self.redis_client.get(key)
                if value:
                    # Les valeurs sont déjà décodées car decode_responses=True
                    result[key.replace(self.hash_prefix, '')] = value
            return result
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération de toutes les associations: {e}")
            return {}

    def search_by_name(self, name: str) -> List[str]:
        """
        Recherche les hashes associés à un nom.
        
        Args:
            name (str): Nom à rechercher
            
        Returns:
            List[str]: Liste des hashes associés au nom
        """
        try:
            return [h.decode('utf-8') for h in self.redis_client.smembers(f"{self.name_prefix}{name}")]
        except Exception as e:
            logger.error(f"Erreur lors de la recherche par nom: {e}")
            return []

    def search_by_letter(self, letter: str) -> List[str]:
        """
        Recherche les noms commençant par une lettre.
        
        Args:
            letter (str): Lettre de début
            
        Returns:
            List[str]: Liste des noms commençant par la lettre
        """
        try:
            return [n.decode('utf-8') for n in self.redis_client.smembers(f"{self.index_prefix}letter:{letter.lower()}")]
        except Exception as e:
            logger.error(f"Erreur lors de la recherche par lettre: {e}")
            return []

    def clear(self) -> bool:
        """Vider le cache."""
        if not self._ensure_connection():
            return False
            
        try:
            self.redis_client.flushdb()
            return True
        except Exception as e:
            logger.warning(f"Erreur lors du nettoyage du cache: {e}")
            return False 