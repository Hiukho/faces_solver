# Lucca Faces Solver

Un outil pour obtenir un score parfait au jeu Lucca Faces en automatisant la reconnaissance et la mémorisation des visages.

## Fonctionnalités

- **Reconnaissance automatique :** Mémorise les visages et les noms associés
- **Apprentissage cumulatif :** Plus vous l'utilisez, meilleure est sa performance
- **Base de données triée :** Les associations sont stockées dans un fichier JSON trié par ordre alphabétique
- **Suivi des performances :** Affiche un résumé du jeu avec score total et précision
- **Interface web :** Une interface intuitive pour utiliser l'outil depuis votre navigateur

## Installation

1. Clonez ce dépôt
2. Installez les dépendances :
   ```
   pip install -r requirements.txt
   ```

## Utilisation

### Via l'interface web (recommandé)

1. Lancez le serveur web :
   ```
   python app.py
   ```
2. Ouvrez votre navigateur à l'adresse `http://localhost:8080`
3. Suivez les instructions à l'écran pour copier une commande cURL depuis le site Lucca Faces
4. Collez la commande cURL dans le formulaire et lancez le jeu
5. Les résultats s'afficheront automatiquement une fois le jeu terminé

### Via le script en ligne de commande

```
python main.py
```

Le script va :
1. Charger les associations hash-nom existantes depuis `faces_data.json` (si présent)
2. Créer un nouveau jeu
3. Récupérer et traiter les 10 questions une par une
4. Utiliser les associations connues pour faire des suppositions précises
5. Enregistrer les nouvelles associations pour les utilisations futures
6. Afficher un résumé des performances avec le score total et la précision

## Données

Les données sont stockées dans un fichier `faces_data.json` qui contient les associations entre les hashes des images et les noms des personnes. Le fichier est trié par ordre alphabétique des noms pour faciliter la lecture.

## Performance

À la fin de chaque exécution, le script affiche :
- Le score total accumulé
- Le nombre de réponses correctes
- Le pourcentage de précision
- Le nombre total d'associations dans la base de données

Plus vous utilisez l'outil, plus sa base de connaissances s'enrichit, améliorant ainsi sa performance au fil du temps.

## Problèmes connus

- L'outil nécessite une connexion internet et un accès au site de Lucca Faces.
- Les performances peuvent varier en fonction de la qualité des images et des variations d'éclairage.

## Contribuer

Les contributions sont les bienvenues ! N'hésitez pas à soumettre des pull requests ou à ouvrir des issues pour améliorer cet outil. 