#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import logging
import base64
import hashlib
import time
import os
from urllib.parse import urljoin

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_existing_data():
    """
    Charge les données existantes du fichier faces_data.json.
    
    Returns:
        dict: Dictionnaire des associations hash-nom
    """
    hash_name_map = {}
    
    try:
        if os.path.exists('faces_data.json'):
            logger.info("Chargement des données existantes de faces_data.json")
            with open('faces_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Convertir la liste en dictionnaire
                for item in data:
                    if 'hash' in item and 'name' in item:
                        hash_name_map[item['hash']] = item['name']
                
            logger.info(f"{len(hash_name_map)} associations hash-nom chargées.")
        else:
            logger.info("Aucun fichier faces_data.json existant. Création d'un nouveau fichier.")
    except Exception as e:
        logger.error(f"Erreur lors du chargement des données existantes: {e}")
    
    return hash_name_map

def save_data(hash_name_map):
    """
    Enregistre les associations hash-nom dans un fichier JSON.
    Les éléments sont triés par nom alphabétique.
    
    Args:
        hash_name_map (dict): Dictionnaire des associations hash-nom
    """
    logger.info(f"Enregistrement de {len(hash_name_map)} associations hash-nom dans faces_data.json")
    
    # Transformer le dictionnaire en format attendu
    json_data = [{"hash": hash_val, "name": name} for hash_val, name in hash_name_map.items()]
    
    # Trier les données par nom alphabétique
    json_data_sorted = sorted(json_data, key=lambda x: x["name"])
    
    with open('faces_data.json', 'w', encoding='utf-8') as f:
        json.dump(json_data_sorted, f, ensure_ascii=False, indent=2)
    
    logger.info("Enregistrement terminé avec succès. Données triées par nom alphabétique.")

def make_guess(game_id, question_id, suggestion_id, headers, cookies):
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

def get_question_image(game_id, question_id, headers, cookies):
    """
    Fonction qui récupère l'image associée à une question.
    
    Args:
        game_id (str): L'ID du jeu
        question_id (int): L'ID de la question
        headers (dict): Les en-têtes HTTP à envoyer
        cookies (dict): Les cookies à inclure dans la requête
        
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
        logger.info(f"Récupération de l'image de la question {question_id}...")
        response = requests.get(url, headers=image_headers, cookies=cookies)
        response.raise_for_status()
        
        # Conversion de l'image en base64
        image_base64 = base64.b64encode(response.content).decode('utf-8')
        
        # Calcul du hash SHA-256 de l'image en base64
        image_hash = hashlib.sha256(image_base64.encode('utf-8')).hexdigest()
        
        logger.info(f"Image récupérée et convertie en base64 avec succès.")
        logger.info(f"Hash SHA-256 de l'image: {image_hash}")
        
        return image_hash
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la récupération de l'image: {e}")
    
    return None

def get_next_question(game_id, headers, cookies):
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
        '_BEAMER_USER_ID_xWDIXXVd32349': 'token',
        '_BEAMER_FIRST_VISIT_xWDIXXVd32349': '2025-03-24T19:58:05.317Z',
        'authToken': 'token'
    }
    
    # Pour s'assurer que le payload est bien envoyé comme JSON
    data = {}
    
    # Charger les associations hash-nom existantes
    hash_name_map = load_existing_data()
    
    # Initialiser le compteur de score
    total_score = 0
    correct_guesses = 0
    total_guesses = 0
    
    try:
        logger.info("Envoi de la requête à l'API pour créer un nouveau jeu...")
        response = requests.post(url, headers=headers, cookies=cookies, json=data)
        response.raise_for_status()
        
        response_json = response.json()
        
        if 'id' in response_json:
            game_id = response_json['id']
            logger.info(f"ID du jeu récupéré: {game_id}")
            
            # Boucle de 10 itérations pour récupérer les questions et faire les guesses
            for i in range(10):
                logger.info(f"Itération {i+1}/10")
                
                # Récupérer la prochaine question
                next_question = get_next_question(game_id, headers, cookies)
                
                # Si nous avons bien récupéré la question
                if next_question and 'id' in next_question:
                    question_id = next_question['id']
                    
                    # Récupérer l'image de la question
                    image_hash = get_question_image(game_id, question_id, headers, cookies)
                    
                    # Créer un dictionnaire pour associer les IDs des suggestions avec leurs valeurs (noms)
                    suggestion_map = {}
                    # Créer un dictionnaire inverse pour associer les noms avec les IDs des suggestions
                    name_suggestion_map = {}
                    if 'suggestions' in next_question:
                        for suggestion in next_question['suggestions']:
                            suggestion_map[suggestion['id']] = suggestion['value']
                            name_suggestion_map[suggestion['value']] = suggestion['id']
                    
                    # Vérifier si le hash existe déjà dans notre base de données
                    known_person = False
                    correct_suggestion_id = None
                    
                    if image_hash in hash_name_map:
                        known_name = hash_name_map[image_hash]
                        logger.info(f"Hash déjà connu! Il correspond à: {known_name}")
                        
                        # Vérifier si le nom connu est dans les suggestions
                        if known_name in name_suggestion_map:
                            correct_suggestion_id = name_suggestion_map[known_name]
                            logger.info(f"Personne connue trouvée dans les suggestions avec l'ID: {correct_suggestion_id}")
                            known_person = True
                    
                    # Faire le guess
                    if 'suggestions' in next_question and len(next_question['suggestions']) > 0:
                        # Si on connaît la personne, on utilise son ID de suggestion pour le guess
                        if known_person and correct_suggestion_id:
                            suggestion_id = correct_suggestion_id
                            logger.info(f"Utilisation de l'ID de suggestion connu: {suggestion_id}")
                        else:
                            # Sinon, on utilise la première suggestion
                            suggestion_id = next_question['suggestions'][0]['id']
                            logger.info(f"Utilisation de la première suggestion: {suggestion_id}")
                        
                        # Faire le guess avec la suggestion choisie
                        guess_result = make_guess(game_id, question_id, suggestion_id, headers, cookies)
                        
                        # Incrémenter le nombre total de guesses
                        total_guesses += 1
                        
                        # Si on a bien reçu un résultat et qu'il contient l'ID de la suggestion correcte
                        if guess_result:
                            # Ajouter le score au total
                            if 'score' in guess_result:
                                question_score = guess_result['score']
                                total_score += question_score
                                logger.info(f"Score pour cette question: {question_score}")
                            
                            # Vérifier si la réponse était correcte
                            if 'isCorrect' in guess_result and guess_result['isCorrect']:
                                correct_guesses += 1
                                logger.info("Réponse correcte! 🎉")
                            
                            if 'correctSuggestionId' in guess_result:
                                correct_suggestion_id = guess_result['correctSuggestionId']
                                
                                # Récupérer le nom correspondant à la suggestion correcte
                                if correct_suggestion_id in suggestion_map:
                                    correct_name = suggestion_map[correct_suggestion_id]
                                    logger.info(f"La réponse correcte est: {correct_name}")
                                    
                                    # Associer le hash de l'image avec le nom correct
                                    if image_hash:
                                        logger.info(f"Association du hash de la photo avec {correct_name}")
                                        
                                        # Ajouter l'association hash-nom au dictionnaire
                                        hash_name_map[image_hash] = correct_name
                                else:
                                    logger.warning(f"ID de suggestion correct {correct_suggestion_id} non trouvé dans les suggestions.")
                    
                    # Petite pause pour éviter de surcharger l'API
                    time.sleep(1)
                else:
                    logger.error("Impossible de récupérer la prochaine question. Arrêt de la boucle.")
                    break
            
            # Enregistrer les associations hash-nom dans un fichier JSON
            save_data(hash_name_map)
            
            # Afficher le résumé des scores
            accuracy = (correct_guesses / total_guesses * 100) if total_guesses > 0 else 0
            logger.info("=" * 50)
            logger.info("RÉSUMÉ DU JEU")
            logger.info("=" * 50)
            logger.info(f"Score total: {total_score} points")
            logger.info(f"Réponses correctes: {correct_guesses}/{total_guesses} ({accuracy:.1f}%)")
            logger.info(f"Nombre total d'associations hash-nom: {len(hash_name_map)}")
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