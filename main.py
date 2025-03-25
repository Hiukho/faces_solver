#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import logging
import base64
import hashlib
import time
import os
import asyncio
import aiohttp
from urllib.parse import urljoin
from cache_manager import CacheManager
from typing import Dict, List, Optional, Tuple, Set

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialisation du gestionnaire de cache
cache_manager = CacheManager()

def make_guess(game_id: str, question_id: int, suggestion_id: int, headers: Dict, cookies: Dict) -> Optional[Dict]:
    """
    Fonction qui envoie une réponse (guess) pour une question.
    
    Args:
        game_id (str): L'ID du jeu
        question_id (int): L'ID de la question
        suggestion_id (int): L'ID de la suggestion sélectionnée
        headers (dict): Les en-têtes HTTP à envoyer
        cookies (dict): Les cookies à inclure dans la requête
        
    Returns:
        dict: La réponse JSON ou None en cas d'erreur
    """
    url = f'https://aramis.ilucca.net/faces/api/games/{game_id}/questions/{question_id}/guess'
    
    # Le payload à envoyer
    data = {
        "questionId": question_id,
        "suggestionId": suggestion_id
    }
    
    try:
        logger.info(f"Envoi de la réponse pour la question {question_id}...")
        response = requests.post(url, headers=headers, cookies=cookies, json=data)
        response.raise_for_status()
        
        response_json = response.json()
        logger.info("Réponse pour le guess reçue avec succès.")
        logger.info(f"Réponse: {json.dumps(response_json, indent=2, ensure_ascii=False)}")
        
        return response_json
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de l'appel API pour le guess: {e}")
    except json.JSONDecodeError:
        logger.error("Erreur lors du décodage de la réponse JSON pour le guess")
        logger.info(f"Contenu de la réponse: {response.text}")
    
    return None

async def get_question_image_async(session: aiohttp.ClientSession, game_id: str, question_id: int, headers: Dict, cookies: Dict) -> Optional[str]:
    """
    Version asynchrone de la fonction get_question_image.
    
    Args:
        session (aiohttp.ClientSession): Session aiohttp
        game_id (str): L'ID du jeu
        question_id (int): L'ID de la question
        headers (dict): Les en-têtes HTTP
        cookies (dict): Les cookies
        
    Returns:
        str: Le hash de l'image en base64 ou None en cas d'erreur
    """
    base_url = 'https://aramis.ilucca.net'
    url = f'{base_url}/faces/api/games/{game_id}/questions/{question_id}/picture'
    
    # Modification des en-têtes pour la requête d'image
    image_headers = headers.copy()
    image_headers.update({
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'priority': 'i',
        'sec-fetch-dest': 'image',
        'sec-fetch-mode': 'no-cors'
    })
    
    try:
        logger.info(f"Récupération asynchrone de l'image de la question {question_id}...")
        async with session.get(url, headers=image_headers, cookies=cookies) as response:
            if response.status == 200:
                image_data = await response.read()
                image_base64 = base64.b64encode(image_data).decode('utf-8')
                image_hash = hashlib.sha256(image_base64.encode('utf-8')).hexdigest()
                logger.info(f"Image {question_id} récupérée et hashée avec succès.")
                return image_hash
            else:
                logger.error(f"Erreur lors de la récupération de l'image {question_id}: {response.status}")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération asynchrone de l'image {question_id}: {e}")
    
    return None

async def fetch_all_images(game_id: str, start_question_id: int, num_questions: int, headers: Dict, cookies: Dict) -> Dict[int, str]:
    """
    Récupère toutes les images de manière asynchrone.
    
    Args:
        game_id (str): L'ID du jeu
        start_question_id (int): ID de la première question
        num_questions (int): Nombre de questions à récupérer
        headers (dict): Les en-têtes HTTP
        cookies (dict): Les cookies
        
    Returns:
        Dict[int, str]: Dictionnaire mapping question_id -> image_hash
    """
    image_hashes = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(num_questions):
            question_id = start_question_id + i
            task = get_question_image_async(session, game_id, question_id, headers, cookies)
            tasks.append((question_id, task))
        
        # Exécuter toutes les tâches en parallèle
        for question_id, task in tasks:
            image_hash = await task
            if image_hash:
                image_hashes[question_id] = image_hash
    
    return image_hashes

def get_next_question(game_id: str, headers: Dict, cookies: Dict) -> Optional[Dict]:
    """
    Fonction qui récupère la prochaine question du jeu.
    
    Args:
        game_id (str): L'ID du jeu obtenu de l'appel précédent
        headers (dict): Les en-têtes HTTP à envoyer
        cookies (dict): Les cookies à inclure dans la requête
        
    Returns:
        dict: La réponse JSON ou None en cas d'erreur
    """
    url = f'https://aramis.ilucca.net/faces/api/games/{game_id}/questions/next'
    
    # Le payload à envoyer
    data = {
        "establishments": [],
        "departments": []
    }
    
    try:
        logger.info(f"Envoi de la requête pour la prochaine question du jeu {game_id}...")
        response = requests.post(url, headers=headers, cookies=cookies, json=data)
        response.raise_for_status()
        
        response_json = response.json()
        logger.info("Réponse pour la prochaine question reçue avec succès.")
        logger.info(f"Réponse: {json.dumps(response_json, indent=2, ensure_ascii=False)}")
        
        return response_json
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de l'appel API pour la prochaine question: {e}")
    except json.JSONDecodeError:
        logger.error("Erreur lors du décodage de la réponse JSON pour la prochaine question")
        logger.info(f"Contenu de la réponse: {response.text}")
    
    return None

def process_question(next_question: Dict, image_hash: str, headers: Dict, cookies: Dict, game_id: str) -> Tuple[bool, Optional[int], Optional[Dict]]:
    """
    Traite une question et retourne les informations nécessaires.
    
    Args:
        next_question (Dict): Les données de la question
        image_hash (str): Le hash de l'image
        headers (Dict): Les en-têtes HTTP
        cookies (Dict): Les cookies
        game_id (str): L'ID du jeu
        
    Returns:
        Tuple[bool, Optional[int], Optional[Dict]]: (succès, suggestion_id, résultat)
    """
    if not next_question or 'id' not in next_question:
        return False, None, None
        
    question_id = next_question['id']
    
    # Créer les dictionnaires de mapping
    suggestion_map = {}
    name_suggestion_map = {}
    if 'suggestions' in next_question:
        for suggestion in next_question['suggestions']:
            suggestion_map[suggestion['id']] = suggestion['value']
            name_suggestion_map[suggestion['value']] = suggestion['id']
    
    # Vérifier le cache Redis
    known_person = False
    correct_suggestion_id = None
    
    try:
        if image_hash:
            known_name = cache_manager.get(image_hash)
            if known_name:
                logger.info(f"Hash déjà connu! Il correspond à: {known_name}")
                
                # Vérifier si le nom connu est dans les suggestions
                if known_name in name_suggestion_map:
                    correct_suggestion_id = name_suggestion_map[known_name]
                    logger.info(f"Personne connue trouvée dans les suggestions avec l'ID: {correct_suggestion_id}")
                    known_person = True
    except Exception as e:
        logger.warning(f"Erreur lors de l'accès au cache Redis: {e}")
        logger.info("Continuation sans utiliser le cache...")
    
    # Faire le guess
    if 'suggestions' in next_question and len(next_question['suggestions']) > 0:
        suggestion_id = correct_suggestion_id if known_person else next_question['suggestions'][0]['id']
        logger.info(f"Utilisation de l'ID de suggestion: {suggestion_id}")
        
        guess_result = make_guess(game_id, question_id, suggestion_id, headers, cookies)
        return True, suggestion_id, guess_result
    
    return False, None, None

def main():
    """
    Fonction principale qui effectue l'appel API et extrait l'ID de la réponse.
    """
    url = 'https://aramis.ilucca.net/faces/api/games'
    
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'content-type': 'application/json',
        'origin': 'https://aramis.ilucca.net',
        'priority': 'u=1, i',
        'referer': 'https://aramis.ilucca.net/faces/game',
        'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'
    }
    
    cookies = {
        '_BEAMER_USER_ID_xWDIXXVd32349': '866ab2c3-8cd5-4172-a352-145f7f6fbc34',
        '_BEAMER_FIRST_VISIT_xWDIXXVd32349': '2025-01-13T14:17:30.055Z',
        'authToken': '4ee94e71-aa02-448d-977a-b8dac41b2007'
    }
    
    # Initialiser les compteurs
    total_score = 0
    correct_guesses = 0
    total_guesses = 0
    
    try:
        logger.info("Envoi de la requête à l'API pour créer un nouveau jeu...")
        response = requests.post(url, headers=headers, cookies=cookies, json={})
        response.raise_for_status()
        
        response_json = response.json()
        
        if 'id' in response_json:
            game_id = response_json['id']
            logger.info(f"ID du jeu récupéré: {game_id}")
            
            # Récupérer la première question pour obtenir son ID
            first_question = get_next_question(game_id, headers, cookies)
            if not first_question or 'id' not in first_question:
                logger.error("Impossible de récupérer la première question")
                return
                
            start_question_id = first_question['id']
            logger.info(f"ID de la première question: {start_question_id}")
            
            # Récupérer toutes les images de manière asynchrone
            logger.info("Récupération asynchrone de toutes les images...")
            image_hashes = asyncio.run(fetch_all_images(game_id, start_question_id, 10, headers, cookies))
            logger.info(f"{len(image_hashes)} images récupérées avec succès")
            
            # Boucle de 10 itérations
            for i in range(10):
                logger.info(f"Itération {i+1}/10")
                
                # Récupérer la prochaine question
                next_question = get_next_question(game_id, headers, cookies)
                if not next_question:
                    continue
                    
                # Récupérer le hash de l'image depuis notre dictionnaire
                image_hash = image_hashes.get(next_question['id'])
                if not image_hash:
                    logger.warning(f"Hash non trouvé pour la question {next_question['id']}")
                    continue
                
                # Traiter la question
                success, suggestion_id, guess_result = process_question(next_question, image_hash, headers, cookies, game_id)
                
                if success and guess_result:
                    total_guesses += 1
                    
                    # Mettre à jour le score
                    if 'score' in guess_result:
                        total_score += guess_result['score']
                        logger.info(f"Score pour cette question: {guess_result['score']}")
                    
                    # Vérifier si la réponse est correcte
                    if guess_result.get('correctSuggestionId') == guess_result.get('suggestionId'):
                        correct_guesses += 1
                        logger.info(f"Réponse correcte ! ({correct_guesses}/{total_guesses})")
                    else:
                        logger.warning(f"Réponse incorrecte. ID correct: {guess_result.get('correctSuggestionId')}, ID fourni: {guess_result.get('suggestionId')}")
                    
                    # Mettre à jour le cache si nécessaire
                    if 'correctSuggestionId' in guess_result:
                        correct_suggestion_id = guess_result['correctSuggestionId']
                        if correct_suggestion_id in suggestion_map:
                            correct_name = suggestion_map[correct_suggestion_id]
                            logger.info(f"La réponse correcte est: {correct_name}")
                            
                            if image_hash:
                                logger.info(f"Association du hash de la photo avec {correct_name}")
                                cache_manager.set(image_hash, correct_name)
                
                # Petite pause pour éviter de surcharger l'API
                time.sleep(1)
            
            # Afficher le résumé
            accuracy = (correct_guesses / total_guesses * 100) if total_guesses > 0 else 0
            logger.info("=" * 50)
            logger.info("RÉSUMÉ DU JEU")
            logger.info("=" * 50)
            logger.info(f"Score total: {total_score} points")
            logger.info(f"Réponses correctes: {correct_guesses}/{total_guesses} ({accuracy:.1f}%)")
            logger.info(f"Nombre total d'associations hash-nom: {len(cache_manager.get_all())}")
            logger.info("=" * 50)
            
        else:
            logger.warning("Aucun ID trouvé dans la réponse.")
            logger.info(f"Réponse complète: {json.dumps(response_json, indent=2)}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de l'appel API: {e}")
    except json.JSONDecodeError:
        logger.error("Erreur lors du décodage de la réponse JSON")
        logger.info(f"Contenu de la réponse: {response.text}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")

if __name__ == "__main__":
    main() 