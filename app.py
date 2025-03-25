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

# Configuration de l'encodage pour le système
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Paramètres en ligne de commande pour le mode verbeux
parser = argparse.ArgumentParser(description='Application Lucca Faces Solver')
parser.add_argument('--verbose', action='store_true', help='Active le mode verbeux (logs détaillés)')
args, unknown = parser.parse_known_args()

# Configuration du logging (niveau WARNING par défaut, INFO si mode verbose)
log_level = logging.INFO if args.verbose else logging.WARNING
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Log au démarrage indiquant le niveau de verbosité
if args.verbose:
    logger.info("Mode verbeux activé - Logs détaillés")
else:
    logger.warning("Mode normal - Logs réduits pour de meilleures performances")

app = Flask(__name__)

def load_data():
    """Charger les données existantes depuis le fichier JSON."""
    data = {}
    try:
        if os.path.exists('faces_data.json'):
            with open('faces_data.json', 'r', encoding='utf-8') as f:
                file_content = json.load(f)
                
                # Vérifier si les données sont au format liste (ancien format)
                if isinstance(file_content, list):
                    # Convertir l'ancien format (liste d'objets) en nouveau format (dictionnaire)
                    for item in file_content:
                        if 'hash' in item and 'name' in item:
                            data[item['hash']] = item['name']
                else:
                    # Si c'est déjà un dictionnaire, l'utiliser directement
                    data = file_content
                    
            logger.info(f"Données existantes chargées. {len(data)} associations hash-nom trouvées.")
        else:
            logger.info("Aucun fichier de données existant. Création d'une nouvelle base de données.")
    except Exception as e:
        logger.error(f"Erreur lors du chargement des données: {e}")
    return data

def save_data(data):
    """Sauvegarder les données dans le fichier JSON, triées par nom."""
    try:
        # Trier les données par nom (clé) en ordre alphabétique
        sorted_data = {k: data[k] for k in sorted(data.keys())}
        
        with open('faces_data.json', 'w', encoding='utf-8') as f:
            json.dump(sorted_data, f, indent=4, ensure_ascii=False)
        logger.info(f"Données sauvegardées avec succès. {len(sorted_data)} associations hash-nom.")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde des données: {e}")

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
    
    # Log minimal pour le suivi des opérations
    logger.info(f"Tentative de guess pour la question {question_id}")
    
    # En mode verbeux uniquement, on log le payload
    if args.verbose:
        logger.debug(f"Payload: {safe_json_dumps(payload)}")
    
    # Essayer les deux URLs possibles
    for url in urls:
        try:
            if args.verbose:
                logger.debug(f"Essai avec l'URL: {url}")
            response = requests.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                # Réduire la verbosité du log pour la réponse
                if args.verbose:
                    logger.debug(f"Réponse reçue: {safe_json_dumps(result)}")
                else:
                    # Version simplifiée, uniquement en mode normal
                    is_correct = result.get("isCorrect", False) or result.get("correct", False)
                    score = result.get("score", 0)
                    logger.info(f"Réponse: {'Correcte' if is_correct else 'Incorrecte'}, Score: {score}")
                return result
            elif response.status_code == 404:
                logger.info(f"URL {url} non trouvée, essai de l'URL alternative")
                continue
            else:
                logger.error(f"Erreur lors de la tentative de supposition: {response.status_code}")
                if args.verbose:
                    logger.error(f"Détails: {response.text}")
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
        
        if args.verbose:
            logger.debug(f"Téléchargement de l'image depuis: {image_url}")
        
        response = requests.get(image_url, headers=headers)
        if response.status_code == 200:
            image_data = response.content
            hash_object = hashlib.sha256(image_data)
            return hash_object.hexdigest()
        else:
            logger.error(f"Erreur lors du téléchargement de l'image: {response.status_code}")
            if args.verbose:
                logger.error(f"Détails: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors du calcul du hash de l'image: {e}")
        return None

def safe_json_dumps(obj):
    """Fonction utilitaire pour convertir un objet en JSON avec gestion des erreurs d'encodage."""
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except UnicodeEncodeError as e:
        logger.error(f"Erreur d'encodage Unicode: {e}")
        # Tentative de conversion en UTF-8
        return json.dumps(str(obj), ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erreur lors de la conversion en JSON: {e}")
        return str(obj)

def get_next_question(game_id, headers):
    """Obtenir la prochaine question du jeu."""
    url = f"https://aramis.ilucca.net/faces/api/games/{game_id}/questions/next"
    
    # Payload vide mais nécessaire pour la requête POST
    payload = {
        "establishments": [],
        "departments": []
    }
    
    if args.verbose:
        logger.debug(f"Envoi de la requête pour la prochaine question à {url}")
        logger.debug(f"Headers: {safe_json_dumps(headers)}")
        logger.debug(f"Payload: {safe_json_dumps(payload)}")
    else:
        logger.info("Récupération de la prochaine question")
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        response_data = response.json()
        # Réduire les logs de réponse API qui sont très volumineux
        if args.verbose:
            logger.debug(f"Réponse pour la prochaine question: {safe_json_dumps(response_data)}")
        return response_data
    else:
        logger.error(f"Erreur lors de la récupération de la question: {response.status_code}")
        if args.verbose:
            logger.error(f"Détails: {response.text}")
        return None

def run_game(curl_data):
    """Exécuter le jeu avec les données de cURL fournies."""
    logs = []
    
    try:
        # Extraire les headers de la commande cURL
        headers = curl_data['headers']
        
        # Charger les données existantes
        data = load_data()
        logs.append(f"Données existantes chargées: {len(data)} associations hash-nom.")
        
        # Stats du jeu
        total_score = 0
        correct_guesses = 0
        total_guesses = 0
        
        # Créer un nouveau jeu
        url = "https://aramis.ilucca.net/faces/api/games"
        response = requests.post(url, headers=headers)
        
        if response.status_code != 200:
            logs.append(f"Erreur lors de la création du jeu: {response.status_code}")
            if args.verbose:
                logs.append(f"Détails: {response.text}")
            return {
                "error": "Impossible de créer un nouveau jeu. Vérifiez votre commande cURL.",
                "logs": logs
            }
        
        game_data = response.json()
        # Ne pas logger la réponse complète sauf en mode verbeux
        if args.verbose:
            logs.append(f"Réponse complète de création du jeu: {safe_json_dumps(game_data)}")
        
        # Extraire l'ID du jeu (compatible avec différentes structures API)
        game_id = None
        if isinstance(game_data, dict):
            game_id = game_data.get("id")
        elif isinstance(game_data, str):
            game_id = game_data
            
        if not game_id:
            logs.append("Impossible d'extraire l'ID du jeu de la réponse API")
            return {
                "error": "Format de réponse API non reconnu",
                "logs": logs
            }
            
        logs.append(f"Nouveau jeu créé avec l'ID: {game_id}")
        
        # Boucle de jeu principale
        for i in range(10):  # Le jeu a 10 questions
            logs.append(f"\n--- Question {i+1}/10 ---")
            
            # Obtenir la prochaine question
            question = get_next_question(game_id, headers)
            # Ne pas logger la réponse complète sauf en mode verbeux
            if args.verbose:
                logs.append(f"Réponse API complète pour la question: {safe_json_dumps(question)}")
            
            if not question:
                logs.append("Impossible d'obtenir la prochaine question. Le jeu s'arrête.")
                break
            
            # Extraire les informations de la question (compatible avec différentes structures API)
            question_id = None
            image_url = None
            suggestions = []
            
            if isinstance(question, dict):
                question_id = question.get("id")
                # Différentes versions API peuvent avoir des champs différents
                image_url = question.get("imageUrl") or question.get("pictureUrl")
                
                # Les suggestions peuvent être dans différents formats selon la version de l'API
                api_suggestions = question.get("suggestions", [])
                if isinstance(api_suggestions, list):
                    suggestions = api_suggestions
            
            if not question_id or not image_url:
                logs.append("Format de question non reconnu. Passage à la suivante.")
                continue
                
            logs.append(f"Question ID: {question_id}")
            if args.verbose:
                logs.append(f"Image URL: {image_url}")
            
            # Afficher les suggestions pour débogage, uniquement en mode verbeux
            if args.verbose and suggestions:
                logs.append("Suggestions disponibles:")
                for suggestion in suggestions:
                    # Les suggestions peuvent être des objets ou des chaînes selon la version de l'API
                    if isinstance(suggestion, dict):
                        suggestion_id = suggestion.get("id")
                        suggestion_value = suggestion.get("value")
                        logs.append(f"  - ID: {suggestion_id}, Valeur: {suggestion_value}")
                    else:
                        logs.append(f"  - Suggestion: {suggestion}")
            elif not suggestions:
                logs.append("Aucune suggestion disponible dans la réponse API.")
            else:
                logs.append(f"{len(suggestions)} suggestions disponibles")
            
            # Calculer le hash de l'image
            image_hash = get_image_hash(image_url, headers)
            if not image_hash:
                logs.append("Impossible de calculer le hash de l'image. Passage à la question suivante.")
                continue
            
            logs.append(f"Hash de l'image: {image_hash[:8]}...") # Afficher seulement le début du hash
            
            # Vérifier si le hash est connu
            suggestion_id = None
            suggestion_value = None
            if image_hash in data:
                person_name = data[image_hash]
                logs.append(f"Hash déjà connu! Cette personne est: {person_name}")
                
                # Rechercher cette personne dans les suggestions
                for suggestion in suggestions:
                    if isinstance(suggestion, dict):
                        if suggestion.get("value", "").lower() == person_name.lower():
                            suggestion_id = suggestion.get("id")
                            suggestion_value = suggestion.get("value")
                            logs.append(f"Suggestion trouvée dans la liste: {suggestion_value}")
                            if args.verbose:
                                logs.append(f"avec ID: {suggestion_id}")
                            break
                    elif isinstance(suggestion, str) and suggestion.lower() == person_name.lower():
                        suggestion_id = suggestions.index(suggestion)  # Utiliser l'index comme ID
                        suggestion_value = suggestion
                        logs.append(f"Suggestion trouvée dans la liste: {suggestion_value}")
                        break
            
            # Si aucune suggestion n'a été trouvée, prendre la première de la liste
            if not suggestion_id and suggestions:
                suggestion = suggestions[0]
                if isinstance(suggestion, dict):
                    suggestion_id = suggestion.get("id")
                    suggestion_value = suggestion.get("value")
                else:
                    suggestion_id = 0  # Premier index
                    suggestion_value = suggestion
                
                logs.append(f"Aucune correspondance trouvée. Utilisation de la première suggestion: {suggestion_value}")
            
            # Faire une supposition
            if suggestion_id is not None:
                total_guesses += 1
                
                # Adapter le format pour l'API
                guess_payload = {}
                if isinstance(suggestions[0], dict):
                    # Format avec ID de suggestion
                    guess_payload = {
                        "questionId": question_id,
                        "suggestionId": suggestion_id
                    }
                else:
                    # Format avec suggestion directe
                    guess_payload = {
                        "suggestion": suggestion_value
                    }
                
                guess_result = make_api_guess(game_id, question_id, guess_payload, headers)
                # Ne pas logger le résultat complet sauf en mode verbeux
                if args.verbose:
                    logs.append(f"Résultat complet du guess: {safe_json_dumps(guess_result)}")
                
                if guess_result:
                    # Extraire les informations de manière flexible pour supporter différentes versions API
                    is_correct = False
                    score = 0
                    correct_name = ""
                    
                    if isinstance(guess_result, dict):
                        # Différentes clés possibles selon la version de l'API
                        is_correct = guess_result.get("isCorrect", False) or guess_result.get("correct", False)
                        score = guess_result.get("score", 0)
                        
                        # Récupérer le nom correct
                        if "correctAnswer" in guess_result:
                            correct_name = guess_result.get("correctAnswer")
                        elif "correctSuggestionId" in guess_result:
                            correct_id = guess_result.get("correctSuggestionId")
                            # Trouver le nom correspondant à l'ID correct
                            for suggestion in suggestions:
                                if isinstance(suggestion, dict) and suggestion.get("id") == correct_id:
                                    correct_name = suggestion.get("value", "")
                                    break
                    
                    total_score += score
                    
                    if is_correct:
                        correct_guesses += 1
                        logs.append(f"Réponse correcte! Score pour cette question: {score}")
                    else:
                        logs.append(f"Réponse incorrecte. La bonne réponse était: {correct_name}. Score: {score}")
                    
                    # Associer le hash avec le nom correct pour les utilisations futures
                    if correct_name:
                        data[image_hash] = correct_name
                        logs.append(f"Association du hash avec le nom '{correct_name}' pour les utilisations futures.")
                else:
                    logs.append("Erreur lors de la soumission de la supposition.")
            else:
                logs.append("Aucune suggestion disponible pour cette question.")
            
            # Petite pause pour éviter de surcharger l'API
            # Réduire le temps d'attente pour plus de rapidité
            time.sleep(0.3)  # Réduit de 0.5 à 0.3 secondes
        
        # Avant la sauvegarde des données mises à jour, filtrer les logs pour éviter des chaînes trop longues ou erreurs d'encodage
        filtered_logs = []
        for log in logs:
            # Vérifier si c'est une chaîne
            if isinstance(log, str):
                # Ajouter directement les logs courts
                if len(log) < 1000:
                    filtered_logs.append(log)
                else:
                    # Tronquer les logs trop longs pour éviter des problèmes d'affichage
                    filtered_logs.append(log[:500] + "... [tronqué]")
            else:
                # Convertir les non-chaînes en chaîne
                try:
                    filtered_logs.append(str(log))
                except:
                    filtered_logs.append("[Impossible d'afficher ce log]")
        
        # Remplacer les logs par les versions filtrées
        logs = filtered_logs
        
        # Sauvegarder les données mises à jour
        save_data(data)
        logs.append("\n--- Résumé du jeu ---")
        logs.append(f"Score total: {total_score}")
        
        # Calcul de la précision
        accuracy = (correct_guesses / total_guesses * 100) if total_guesses > 0 else 0
        accuracy_formatted = f"{accuracy:.1f}%"
        
        logs.append(f"Réponses correctes: {correct_guesses}/{total_guesses} ({accuracy_formatted})")
        logs.append(f"Associations dans la base de données: {len(data)}")
        
        return {
            "total_score": total_score,
            "correct_guesses": correct_guesses,
            "total_guesses": total_guesses,
            "accuracy": accuracy_formatted,
            "hash_name_count": len(data),
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"Erreur lors de l'exécution du jeu: {str(e)}")
        import traceback
        logs.append(f"Détails de l'erreur: {traceback.format_exc()}")
        return {
            "error": f"Erreur: {str(e)}",
            "logs": logs
        }

@app.route('/')
def index():
    """Page d'accueil de l'application."""
    return render_template('index.html')

@app.route('/run', methods=['POST'])
def run():
    """Endpoint pour exécuter le jeu avec une commande cURL."""
    curl_command = request.form.get('curl_command', '')
    
    if not curl_command:
        return jsonify({
            "error": "Aucune commande cURL fournie.",
            "logs": ["Erreur: Aucune commande cURL fournie."]
        })
    
    try:
        curl_data = parse_curl(curl_command)
        result = run_game(curl_data)
        # Utiliser json.dumps avec ensure_ascii=False pour préserver les caractères UTF-8
        response = app.response_class(
            response=json.dumps(result, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
        return response
    except Exception as e:
        error_result = {
            "error": f"Erreur lors du traitement de la commande cURL: {str(e)}",
            "logs": [f"Erreur lors du traitement de la commande cURL: {str(e)}"]
        }
        response = app.response_class(
            response=json.dumps(error_result, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
        return response

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
    app.run(debug=True, host='0.0.0.0', port=8080) 
