#!/bin/bash

# Activer l'environnement virtuel
source .venv/bin/activate

# Exporter les variables d'environnement Flask
export FLASK_APP=app.py
export FLASK_ENV=development

# Lancer l'application Flask
flask run --host=0.0.0.0 --port=8080 