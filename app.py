#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import io
from flask import Flask, render_template, request, jsonify, send_file
import re
import json
import base64
import hashlib
import time
import os
import logging
import requests
import importlib.util
from urllib.parse import urljoin
import argparse
from cache_manager import CacheManager

# Configuration de l'encodage pour le système
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Initialisation du gestionnaire de cache Redis
cache_manager = CacheManager()

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Variables globales pour stocker les IDs de question
last_known_question_id = None
cached_image_hashes = {}

def load_data():
    """Charger les données existantes depuis Redis et le fichier JSON."""
    data = {}
    try:
        # Charger depuis Redis si disponible
        redis_data = cache_manager.get_all()
        if redis_data:
            data.update(redis_data)
        
        # Charger depuis le fichier JSON (backup)
        if os.path.exists('faces_data.json'):
            with open('faces_data.json', 'r', encoding='utf-8') as f:
                file_content = json.load(f)
                
                # Vérifier si les données sont au format liste (ancien format)
                if isinstance(file_content, list):
                    # Convertir l'ancien format (liste d'objets) en nouveau format (dictionnaire)
                    for item in file_content:
                        if 'hash' in item and 'name' in item:
                            data[item['hash']] = item['name']
                            # Mettre à jour Redis si disponible
                            cache_manager.set(item['hash'], item['name'])
                else:
                    # Si c'est déjà un dictionnaire, l'utiliser directement
                    for hash_key, name in file_content.items():
                        if hash_key not in data:  # Ne pas écraser les données Redis
                            data[hash_key] = name
                            # Mettre à jour Redis si disponible
                            cache_manager.set(hash_key, name)
    except Exception as e:
        logger.warning(f"Erreur lors du chargement des données: {e}")
    return data

def save_data(data):
    """Sauvegarder les données dans Redis et le fichier JSON, triées par nom."""
    try:
        # Trier les données par nom (clé) en ordre alphabétique
        sorted_data = {k: data[k] for k in sorted(data.keys())}
        
        # Sauvegarder dans Redis si disponible
        for hash_key, name in sorted_data.items():
            cache_manager.set(hash_key, name)
        
        # Sauvegarder dans le fichier JSON (backup)
        with open('faces_data.json', 'w', encoding='utf-8') as f:
            json.dump(sorted_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Erreur lors de la sauvegarde des données: {e}")

def parse_curl(curl_command):
    """Extraire les headers et cookies d'une commande cURL."""
    headers = {}
    
    # Recherche des en-têtes
    header_pattern = r'-H\s+[\'"]([^:]+):\s*([^\'"]+)[\'"]'
    headers_matches = re.findall(header_pattern, curl_command)
    
    for key, value in headers_matches:
        headers[key.strip()] = value.strip()
    
    # Recherche des cookies (option -b)
    cookie_pattern = r'-b\s+[\'"]([^\'"]+)[\'"]'
    cookie_matches = re.search(cookie_pattern, curl_command)
    
    if cookie_matches:
        cookie_str = cookie_matches.group(1)
        # Ajouter les cookies dans les headers
        headers['Cookie'] = cookie_str
    
    # Recherche de l'URL
    url_match = re.search(r'curl\s+[\'"]([^\'"]+)[\'"]', curl_command)
    if not url_match:
        url_match = re.search(r'curl\s+([^\s]+)', curl_command)
    
    url = url_match.group(1) if url_match else None
    
    # Vérification de la présence des cookies essentiels
    if 'Cookie' not in headers:
        raise ValueError("Les cookies d'authentification sont manquants dans la commande cURL.")
    
    return {
        'url': url,
        'headers': headers
    }

def make_api_guess(game_id, question_id, payload, headers):
    """Faire une supposition pour une question donnée avec un payload flexible."""
    # L'URL peut être soit /guess (singulier) soit /guesses (pluriel) selon la version de l'API
    urls = [
        f"https://aramis.ilucca.net/faces/api/games/{game_id}/questions/{question_id}/guess",
        f"https://aramis.ilucca.net/faces/api/games/{game_id}/questions/{question_id}/guesses"
    ]
    
    # Essayer les deux URLs possibles
    for url in urls:
        try:
            response = requests.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                continue
            else:
                logger.error(f"Erreur lors de la tentative de supposition: {response.status_code}")
        except Exception as e:
            logger.error(f"Exception lors de l'appel API: {str(e)}")
    
    # Si aucune URL n'a fonctionné
    return None

def get_image_hash(image_url, headers):
    """Télécharger une image et calculer son hash SHA-256."""
    try:
        # Vérifier si l'URL est relative (commence par /)
        if image_url.startswith('/'):
            # Ajouter le domaine de base
            image_url = f"https://aramis.ilucca.net{image_url}"
        
        response = requests.get(image_url, headers=headers)
        if response.status_code == 200:
            image_data = response.content
            hash_object = hashlib.sha256(image_data)
            return hash_object.hexdigest()
        else:
            logger.error(f"Erreur lors du téléchargement de l'image: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors du calcul du hash de l'image: {e}")
        return None

def get_image_url_from_question_id(question_id, headers):
    """Récupérer l'URL de l'image pour un ID de question donné."""
    url = f"https://aramis.ilucca.net/faces/api/questions/{question_id}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            question_data = response.json()
            return question_data.get("imageUrl") or question_data.get("pictureUrl")
        else:
            logger.error(f"Erreur lors de la récupération de l'image pour la question {question_id}: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Exception lors de la récupération de l'image: {str(e)}")
        return None

def precache_images(start_question_id, headers, num_questions=10):
    """Précalculer les hash des images pour les prochaines questions."""
    global cached_image_hashes
    cached_image_hashes = {}
    data = load_data()
    
    logger.info(f"Précalcul des hash pour les questions {start_question_id} à {start_question_id + num_questions - 1}")
    
    for i in range(num_questions):
        question_id = start_question_id + i
        image_url = get_image_url_from_question_id(question_id, headers)
        
        if image_url:
            image_hash = get_image_hash(image_url, headers)
            if image_hash:
                cached_image_hashes[question_id] = {
                    "hash": image_hash,
                    "name": data.get(image_hash)
                }
                logger.info(f"Image pour la question {question_id} mise en cache. Hash: {image_hash[:8]}...")
            else:
                logger.warning(f"Impossible de calculer le hash pour la question {question_id}")
        else:
            logger.warning(f"Impossible de récupérer l'URL de l'image pour la question {question_id}")
    
    # Afficher un résumé
    cache_hits = sum(1 for info in cached_image_hashes.values() if info.get("name"))
    logger.info(f"Précalcul terminé. {len(cached_image_hashes)} images en cache, dont {cache_hits} déjà connues.")
    
    return cached_image_hashes

def get_first_question_id(headers):
    """Lancer une partie pour récupérer l'ID de la première question."""
    global last_known_question_id
    
    # Créer un nouveau jeu
    url = "https://aramis.ilucca.net/faces/api/games"
    response = requests.post(url, headers=headers)
    
    if response.status_code != 200:
        logger.error(f"Erreur lors de la création du jeu: {response.status_code}")
        return None
    
    # Extraire l'ID du jeu
    game_data = response.json()
    game_id = game_data.get("id") if isinstance(game_data, dict) else game_data
    
    if not game_id:
        logger.error("Impossible d'extraire l'ID du jeu")
        return None
    
    # Obtenir la première question
    question = get_next_question(game_id, headers)
    if not question or not isinstance(question, dict):
        logger.error("Impossible d'obtenir la première question")
        return None
    
    question_id = question.get("id")
    if question_id:
        last_known_question_id = question_id
        logger.info(f"Premier ID de question récupéré: {question_id}")
    
    return question_id

def get_next_question(game_id, headers):
    """Obtenir la prochaine question du jeu."""
    url = f"https://aramis.ilucca.net/faces/api/games/{game_id}/questions/next"
    
    # Payload vide mais nécessaire pour la requête POST
    payload = {
        "establishments": [],
        "departments": []
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"Erreur lors de la récupération de la question: {response.status_code}")
        return None

def run_game_optimized(headers, game_number=1, total_games=5):
    """Exécuter plusieurs parties optimisées avec précalcul des images."""
    logs = []
    try:
        # Charger les données existantes
        data = load_data()
        logs.append(f"Données chargées: {len(data)} associations hash-nom")
        
        # Résultats cumulés
        total_stats = {
            "total_score": 0,
            "correct_guesses": 0,
            "total_guesses": 0,
            "games_completed": 0,
            "games_attempted": total_games,
            "logs": logs
        }
        
        # Récupérer l'ID de la première question si nécessaire
        global last_known_question_id
        if not last_known_question_id:
            first_question_id = get_first_question_id(headers)
            if not first_question_id:
                logs.append("Impossible de déterminer l'ID de la première question")
                return {"error": "Impossible de déterminer l'ID de la première question", "logs": logs}
            last_known_question_id = first_question_id
            logs.append(f"Premier ID de question déterminé: {first_question_id}")
        
        # Exécuter les parties
        for game_num in range(total_games):
            logs.append(f"\n--- Partie {game_num + 1}/{total_games} ---")
            
            # Lancer la partie
            game_result = run_single_game(headers, last_known_question_id, data)
            
            if "error" in game_result:
                logs.append(f"Erreur lors de la partie {game_num + 1}: {game_result['error']}")
                continue
            
            # Mettre à jour les statistiques cumulées
            total_stats["total_score"] += game_result.get("total_score", 0)
            total_stats["correct_guesses"] += game_result.get("correct_guesses", 0)
            total_stats["total_guesses"] += game_result.get("total_guesses", 0)
            total_stats["games_completed"] += 1
            
            if "logs" in game_result:
                logs.extend(game_result["logs"])
            
            logs.append(f"Partie {game_num + 1} terminée: Score {game_result.get('total_score', 0)}, "
                        f"Correctes {game_result.get('correct_guesses', 0)}/{game_result.get('total_guesses', 0)}")
            
            # Attendre un peu entre les parties
            if game_num < total_games - 1:
                time.sleep(0.5)
        
        # Calculer la précision globale
        if total_stats["total_guesses"] > 0:
            accuracy = (total_stats["correct_guesses"] / total_stats["total_guesses"]) * 100
            total_stats["accuracy"] = f"{accuracy:.1f}%"
        else:
            total_stats["accuracy"] = "0.0%"
        
        # Ajouter des statistiques supplémentaires
        total_stats["hash_name_count"] = len(data)
        logs.append(f"\n--- Résumé ---")
        logs.append(f"Score total: {total_stats['total_score']}")
        logs.append(f"Réponses correctes: {total_stats['correct_guesses']}/{total_stats['total_guesses']} ({total_stats['accuracy']})")
        logs.append(f"Parties terminées: {total_stats['games_completed']}/{total_stats['games_attempted']}")
        logs.append(f"Associations hash-nom en base: {total_stats['hash_name_count']}")
        
        # Sauvegarder les données mises à jour
        save_data(data)
        logs.append("Données sauvegardées avec succès")
        
        total_stats["logs"] = logs
        return total_stats
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution des parties: {str(e)}")
        logs.append(f"Erreur critique: {str(e)}")
        return {"error": f"Erreur: {str(e)}", "logs": logs}

def run_single_game(headers, estimated_question_id, data):
    """Exécuter une seule partie en utilisant les hash précalculés."""
    # Initialiser les statistiques et les logs
    game_stats = {
        "total_score": 0,
        "correct_guesses": 0,
        "total_guesses": 0,
        "logs": []
    }
    logs = game_stats["logs"]
    
    try:
        # Créer un nouveau jeu
        url = "https://aramis.ilucca.net/faces/api/games"
        response = requests.post(url, headers=headers)
        
        if response.status_code != 200:
            logs.append(f"Erreur lors de la création du jeu: {response.status_code}")
            return {"error": "Impossible de créer un nouveau jeu", "logs": logs}
        
        # Extraire l'ID du jeu
        game_data = response.json()
        game_id = game_data.get("id") if isinstance(game_data, dict) else game_data
        
        if not game_id:
            logs.append("Format de réponse API non reconnu")
            return {"error": "Format de réponse API non reconnu", "logs": logs}
            
        logs.append(f"Nouveau jeu créé avec ID: {game_id}")
        
        # Boucle principale du jeu (10 questions)
        for i in range(10):
            logs.append(f"Question {i+1}/10")
            
            # Obtenir la prochaine question
            question = get_next_question(game_id, headers)
            if not question:
                logs.append("Impossible d'obtenir la prochaine question")
                break
            
            # Extraire les informations de la question
            question_id = question.get("id") if isinstance(question, dict) else None
            suggestions = question.get("suggestions", []) if isinstance(question, dict) else []
            
            if not question_id or not suggestions:
                logs.append("Format de question invalide, passage à la suivante")
                continue
            
            logs.append(f"Question ID: {question_id}")
            
            # Si c'est la première question, mettre à jour last_known_question_id
            if i == 0:
                global last_known_question_id
                last_known_question_id = question_id
                logs.append(f"ID de question mis à jour: {question_id}")
                
            # Vérifier si nous avons un hash précalculé pour cette question
            cached_info = cached_image_hashes.get(question_id)
            image_hash = None
            person_name = None
            
            if cached_info:
                image_hash = cached_info.get("hash")
                person_name = cached_info.get("name")
                logs.append(f"Hash trouvé en cache: {image_hash[:8]}...")
                
                # Si nous n'avons pas de nom mais avons un hash, vérifier dans les données
                if not person_name and image_hash and image_hash in data:
                    person_name = data[image_hash]
                    # Mettre à jour le cache
                    cached_info["name"] = person_name
                    logs.append(f"Nom trouvé pour ce hash: {person_name}")
            else:
                # Fallback: récupérer l'URL de l'image depuis la question
                logs.append("Hash non trouvé en cache, récupération de l'image...")
                image_url = question.get("imageUrl") or question.get("pictureUrl")
                if image_url:
                    image_hash = get_image_hash(image_url, headers)
                    if image_hash:
                        logs.append(f"Hash calculé: {image_hash[:8]}...")
                        if image_hash in data:
                            person_name = data[image_hash]
                            logs.append(f"Nom trouvé pour ce hash: {person_name}")
                    else:
                        logs.append("Impossible de calculer le hash")
                else:
                    logs.append("URL d'image non trouvée dans la question")
            
            # Trouver la suggestion correspondante
            suggestion_id = None
            if person_name:
                for suggestion in suggestions:
                    if isinstance(suggestion, dict):
                        if suggestion.get("value", "").lower() == person_name.lower():
                            suggestion_id = suggestion.get("id")
                            logs.append(f"Suggestion trouvée: {person_name}")
                            break
                
                if suggestion_id is None:
                    logs.append(f"Nom '{person_name}' non trouvé dans les suggestions")
            
            # Si aucune correspondance, utiliser la première suggestion
            if suggestion_id is None and suggestions:
                suggestion = suggestions[0]
                suggestion_id = suggestion.get("id") if isinstance(suggestion, dict) else 0
                suggestion_value = suggestion.get("value") if isinstance(suggestion, dict) else suggestion
                logs.append(f"Utilisation de la première suggestion: {suggestion_value}")
            
            # Faire une supposition
            if suggestion_id is not None:
                game_stats["total_guesses"] += 1
                
                # Préparer le payload
                guess_payload = {"questionId": question_id, "suggestionId": suggestion_id}
                
                # Envoyer la supposition
                guess_result = make_api_guess(game_id, question_id, guess_payload, headers)
                
                if guess_result:
                    # Vérifier si la réponse est correcte
                    is_correct = guess_result.get('suggestionId') == guess_result.get('correctSuggestionId')
                    score = guess_result.get("score", 0)
                    
                    # Récupérer le nom correct
                    correct_name = ""
                    correct_id = guess_result.get("correctSuggestionId")
                    
                    if correct_id:
                        for suggestion in suggestions:
                            if isinstance(suggestion, dict) and suggestion.get("id") == correct_id:
                                correct_name = suggestion.get("value", "")
                                break
                    
                    # Mettre à jour les statistiques
                    game_stats["total_score"] += score
                    if is_correct:
                        game_stats["correct_guesses"] += 1
                        logs.append(f"Réponse correcte ! Score: {score}")
                    else:
                        logs.append(f"Réponse incorrecte. La bonne réponse était: {correct_name}. Score: {score}")
                    
                    # Mettre à jour le cache avec le nom correct
                    if image_hash and correct_name:
                        data[image_hash] = correct_name
                        try:
                            cache_manager.set(image_hash, correct_name)
                            logs.append(f"Association mise à jour: {image_hash[:8]}... -> {correct_name}")
                        except Exception as e:
                            logs.append(f"Erreur lors de la mise à jour du cache: {str(e)}")
                else:
                    logs.append("Erreur lors de la supposition")
            else:
                logs.append("Aucune suggestion disponible")
            
            # Petit délai pour éviter de surcharger l'API
            time.sleep(0.1)
        
        return game_stats
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution de la partie: {str(e)}")
        logs.append(f"Erreur: {str(e)}")
        return {"error": f"Erreur: {str(e)}", "logs": logs}

def run_game(curl_data):
    """Exécuter le jeu avec les données de cURL fournies."""
    headers = curl_data['headers']
    return run_game_optimized(headers)

@app.route('/')
def index():
    """Page d'accueil avec le formulaire de cURL."""
    return render_template('index.html')

@app.route('/run', methods=['POST'])
def run():
    """Exécuter le jeu avec les données de cURL fournies."""
    try:
        # Tenter de récupérer les données au format JSON ou formulaire
        if request.is_json:
            curl_data = request.get_json()
            curl_command = curl_data.get('curl_command', '')
        else:
            # Formulaire HTML standard
            curl_command = request.form.get('curl_command', '')
            
        if not curl_command:
            return jsonify({"error": "Commande cURL manquante"}), 400
        
        # Parser la commande cURL
        try:
            parsed_data = parse_curl(curl_command)
            if not parsed_data:
                return jsonify({"error": "Format de commande cURL invalide"}), 400
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        
        # Exécuter le jeu optimisé (5 parties)
        result = run_game_optimized(parsed_data['headers'], total_games=5)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution du jeu: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/stats')
def stats():
    """Afficher les statistiques du cache."""
    try:
        data = load_data()
        return jsonify({
            "total_associations": len(data),
            "cached_images": len(cached_image_hashes),
            "associations": data
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/download_data')
def download_data():
    """Télécharger le fichier faces_data.json."""
    try:
        if os.path.exists('faces_data.json'):
            # Renvoyer le fichier faces_data.json en tant que pièce jointe téléchargeable
            return send_file(
                'faces_data.json',
                mimetype='application/json',
                as_attachment=True,
                download_name='faces_data.json'
            )
        else:
            return jsonify({
                "error": "Le fichier faces_data.json n'existe pas encore."
            }), 404
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du fichier: {str(e)}")
        return jsonify({
            "error": f"Erreur lors du téléchargement: {str(e)}"
        }), 500

@app.route('/upload_data', methods=['POST'])
def upload_data():
    """Importer un fichier faces_data.json."""
    try:
        if 'file' not in request.files:
            return jsonify({
                "error": "Aucun fichier n'a été fourni"
            }), 400
            
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                "error": "Aucun fichier sélectionné"
            }), 400
            
        if file and file.filename.endswith('.json'):
            # Sauvegarder une copie de sauvegarde du fichier actuel s'il existe
            if os.path.exists('faces_data.json'):
                backup_filename = f'faces_data_backup_{int(time.time())}.json'
                os.rename('faces_data.json', backup_filename)
                logger.info(f"Sauvegarde du fichier existant créée: {backup_filename}")
                
            # Sauvegarder le nouveau fichier
            file.save('faces_data.json')
            
            # Charger le fichier pour vérifier son contenu
            try:
                with open('faces_data.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Vérifier si le format est correct (dictionnaire ou liste)
                count = 0
                if isinstance(data, dict):
                    count = len(data)
                elif isinstance(data, list):
                    count = len(data)
                    # Convertir au nouveau format
                    new_data = {}
                    for item in data:
                        if 'hash' in item and 'name' in item:
                            new_data[item['hash']] = item['name']
                    
                    # Sauvegarder au nouveau format
                    with open('faces_data.json', 'w', encoding='utf-8') as f:
                        json.dump(new_data, f, indent=4, ensure_ascii=False)
                    count = len(new_data)
                
                return jsonify({
                    "success": True,
                    "message": f"Fichier importé avec succès. {count} associations hash-nom chargées."
                })
            except json.JSONDecodeError:
                # Si le fichier n'est pas un JSON valide, restaurer la sauvegarde
                if os.path.exists(backup_filename):
                    os.rename(backup_filename, 'faces_data.json')
                return jsonify({
                    "error": "Le fichier n'est pas un JSON valide."
                }), 400
        else:
            return jsonify({
                "error": "Le fichier doit être au format JSON"
            }), 400
            
    except Exception as e:
        logger.error(f"Erreur lors de l'importation du fichier: {str(e)}")
        return jsonify({
            "error": f"Erreur lors de l'importation: {str(e)}"
        }), 500

if __name__ == '__main__':
    # Utiliser le port fourni par Cloud Run ou 5000 par défaut
    port = int(os.getenv('PORT', '8080'))
    app.run(host='0.0.0.0', port=port) 
