#!/usr/bin/env python3
"""
Prédicteur de temps d'extraction basé sur une régression bayésienne.

Utilise les caractéristiques du BC pour estimer le temps de traitement
avec un intervalle de confiance.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, Optional
import pickle

# Fichier de données historiques
DATA_FILE = Path(__file__).parent / "extraction_times.json"
MODEL_FILE = Path(__file__).parent / "time_model.pkl"


class BayesianTimePredictor:
    """
    Régression linéaire bayésienne pour prédire le temps d'extraction.
    
    Features utilisées:
    - Taille du texte (caractères)
    - Nombre de produits estimé
    - Nombre de dates détectées (multi-commandes)
    - Type de fichier (PDF=1, HTML=0.5, TXT=0.3)
    
    Retourne:
    - Temps estimé (secondes)
    - Intervalle de confiance (±X secondes)
    """
    
    def __init__(self):
        # Hyperparamètres prior (avant observations)
        self.prior_mean = np.array([0.01, 2.0, 10.0, 5.0, 30.0])  # [text_size, nb_products, nb_dates, file_type, intercept]
        self.prior_precision = np.eye(5) * 0.1  # Faible confiance initiale
        
        # Paramètres posterior (après observations)
        self.posterior_mean = self.prior_mean.copy()
        self.posterior_precision = self.prior_precision.copy()
        
        # Variance du bruit (sigma²)
        self.noise_variance = 100.0  # Initialement élevée
        
        # Historique des observations
        self.observations = []
        
        # Charger le modèle existant
        self._load_model()
    
    def _load_model(self):
        """Charge le modèle sauvegardé s'il existe"""
        if MODEL_FILE.exists():
            try:
                with open(MODEL_FILE, 'rb') as f:
                    data = pickle.load(f)
                    self.posterior_mean = data['mean']
                    self.posterior_precision = data['precision']
                    self.noise_variance = data['noise_variance']
                    self.observations = data.get('observations', [])
                print(f"📊 Modèle chargé: {len(self.observations)} observations")
            except Exception as e:
                print(f"⚠️ Erreur chargement modèle: {e}")
    
    def _save_model(self):
        """Sauvegarde le modèle"""
        try:
            MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(MODEL_FILE, 'wb') as f:
                pickle.dump({
                    'mean': self.posterior_mean,
                    'precision': self.posterior_precision,
                    'noise_variance': self.noise_variance,
                    'observations': self.observations
                }, f)
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde modèle: {e}")
    
    def extract_features(self, text: str, file_type: str = "pdf") -> np.ndarray:
        """
        Extrait les features du texte pour la prédiction.
        
        Args:
            text: Texte extrait du BC
            file_type: Type de fichier (pdf, html, txt)
        
        Returns:
            Vecteur de features [text_size, nb_products, nb_dates, file_type, 1]
        """
        import re
        
        # Taille du texte (en milliers de caractères)
        text_size = len(text) / 1000.0
        
        # Nombre de produits estimé (codes 5-6 chiffres)
        product_codes = re.findall(r'^\s*\d{5,6}\s*$', text, re.MULTILINE)
        nb_products = len(product_codes)
        
        # Nombre de dates de livraison uniques
        date_patterns = [
            r'(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+\d{1,2}\s+(?:jan|fév|mar|avr|mai|juin|juil|août|sep|oct|nov|déc)[a-z]*\.?\s+\d{4}',
            r'\d{2}/\d{2}/\d{4}'
        ]
        dates = []
        for pattern in date_patterns:
            dates.extend(re.findall(pattern, text, re.IGNORECASE))
        nb_dates = len(set(dates)) or 1
        
        # Type de fichier (facteur de complexité)
        file_type_factor = {
            'pdf': 1.0,
            'html': 0.7,
            'htm': 0.7,
            'txt': 0.5
        }.get(file_type.lower(), 1.0)
        
        # Vecteur de features avec terme constant
        return np.array([text_size, nb_products, nb_dates, file_type_factor, 1.0])
    
    def predict(self, text: str, file_type: str = "pdf") -> Dict:
        """
        Prédit le temps d'extraction avec intervalle de confiance.
        
        Args:
            text: Texte du BC
            file_type: Type de fichier
        
        Returns:
            {
                'estimated_time': float,  # Temps estimé (secondes)
                'confidence_interval': (float, float),  # Intervalle [min, max]
                'uncertainty': float,  # Écart-type
                'features': dict  # Features utilisées
            }
        """
        # Extraire les features
        x = self.extract_features(text, file_type)
        
        # Prédiction moyenne
        mean_prediction = np.dot(x, self.posterior_mean)
        
        # Variance de la prédiction (incertitude)
        posterior_cov = np.linalg.inv(self.posterior_precision)
        predictive_variance = self.noise_variance + np.dot(x, np.dot(posterior_cov, x))
        uncertainty = np.sqrt(predictive_variance)
        
        # Assurer un minimum raisonnable
        mean_prediction = max(5.0, mean_prediction)
        
        # Intervalle de confiance à 95%
        ci_lower = max(5.0, mean_prediction - 1.96 * uncertainty)
        ci_upper = mean_prediction + 1.96 * uncertainty
        
        return {
            'estimated_time': round(mean_prediction, 1),
            'confidence_interval': (round(ci_lower, 1), round(ci_upper, 1)),
            'uncertainty': round(uncertainty, 1),
            'features': {
                'text_size_k': round(x[0], 2),
                'nb_products': int(x[1]),
                'nb_dates': int(x[2]),
                'file_type_factor': x[3]
            }
        }
    
    def format_prediction(self, prediction: Dict) -> str:
        """Formate la prédiction pour affichage"""
        time = prediction['estimated_time']
        ci = prediction['confidence_interval']
        
        if time < 60:
            time_str = f"{time:.0f}s"
            ci_str = f"{ci[0]:.0f}s - {ci[1]:.0f}s"
        else:
            time_str = f"{time/60:.1f}min"
            ci_str = f"{ci[0]/60:.1f}min - {ci[1]/60:.1f}min"
        
        return f"⏱️ Temps estimé: {time_str} (intervalle: {ci_str})"
    
    def update(self, text: str, file_type: str, actual_time: float):
        """
        Met à jour le modèle avec une nouvelle observation.
        
        Utilise la mise à jour bayésienne:
        posterior ∝ likelihood × prior
        
        Args:
            text: Texte du BC
            file_type: Type de fichier
            actual_time: Temps réel observé (secondes)
        """
        # Features
        x = self.extract_features(text, file_type)
        
        # Mise à jour bayésienne de la précision et moyenne
        # Formule: precision_new = precision_old + x @ x.T / sigma²
        # Formule: mean_new = precision_new^-1 @ (precision_old @ mean_old + x * y / sigma²)
        
        x = x.reshape(-1, 1)  # Vecteur colonne
        
        self.posterior_precision += np.dot(x, x.T) / self.noise_variance
        
        posterior_cov = np.linalg.inv(self.posterior_precision)
        self.posterior_mean = np.dot(
            posterior_cov,
            np.dot(self.prior_precision, self.prior_mean) + x.flatten() * actual_time / self.noise_variance
        )
        
        # Mise à jour de la variance du bruit (estimation empirique)
        prediction = np.dot(x.flatten(), self.posterior_mean)
        residual = actual_time - prediction
        
        # Moyenne mobile de la variance
        n = len(self.observations) + 1
        self.noise_variance = (self.noise_variance * (n - 1) + residual**2) / n
        self.noise_variance = max(10.0, self.noise_variance)  # Minimum
        
        # Sauvegarder l'observation
        self.observations.append({
            'timestamp': datetime.now().isoformat(),
            'features': x.flatten().tolist(),
            'actual_time': actual_time,
            'predicted_time': prediction
        })
        
        # Sauvegarder le modèle
        self._save_model()
        
        print(f"📈 Modèle mis à jour: {len(self.observations)} observations")
    
    def get_stats(self) -> Dict:
        """Retourne les statistiques du modèle"""
        if not self.observations:
            return {
                'nb_observations': 0,
                'mean_error': None,
                'coefficients': self.posterior_mean.tolist()
            }
        
        # Calculer l'erreur moyenne
        errors = []
        for obs in self.observations:
            errors.append(abs(obs['actual_time'] - obs['predicted_time']))
        
        return {
            'nb_observations': len(self.observations),
            'mean_error': round(np.mean(errors), 1),
            'std_error': round(np.std(errors), 1),
            'noise_variance': round(self.noise_variance, 1),
            'coefficients': {
                'text_size': round(self.posterior_mean[0], 4),
                'nb_products': round(self.posterior_mean[1], 4),
                'nb_dates': round(self.posterior_mean[2], 4),
                'file_type': round(self.posterior_mean[3], 4),
                'intercept': round(self.posterior_mean[4], 4)
            }
        }


# Instance globale
predictor = BayesianTimePredictor()


def predict_extraction_time(text: str, file_type: str = "pdf") -> Dict:
    """Fonction utilitaire pour prédire le temps d'extraction"""
    return predictor.predict(text, file_type)


def record_extraction_time(text: str, file_type: str, actual_time: float):
    """Fonction utilitaire pour enregistrer un temps d'extraction"""
    predictor.update(text, file_type, actual_time)


# CLI pour tests
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Prédicteur de temps d'extraction bayésien")
    parser.add_argument('--predict', type=str, help="Fichier à analyser pour prédiction")
    parser.add_argument('--stats', action='store_true', help="Afficher les statistiques du modèle")
    parser.add_argument('--simulate', action='store_true', help="Simuler des données d'entraînement")
    
    args = parser.parse_args()
    
    if args.stats:
        stats = predictor.get_stats()
        print("\n📊 STATISTIQUES DU MODÈLE")
        print("=" * 40)
        print(f"Observations: {stats['nb_observations']}")
        if stats['mean_error']:
            print(f"Erreur moyenne: {stats['mean_error']}s (±{stats['std_error']}s)")
        print(f"\nCoefficients:")
        for k, v in stats.get('coefficients', {}).items():
            print(f"  {k}: {v}")
    
    elif args.predict:
        import fitz
        
        file_path = Path(args.predict)
        if file_path.suffix.lower() == '.pdf':
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            file_type = "pdf"
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            file_type = file_path.suffix.lower().replace('.', '')
        
        prediction = predictor.predict(text, file_type)
        
        print(f"\n📄 Fichier: {file_path.name}")
        print(f"📏 Taille: {len(text)} caractères")
        print(f"\n{predictor.format_prediction(prediction)}")
        print(f"\n📋 Détails:")
        print(f"   Produits détectés: {prediction['features']['nb_products']}")
        print(f"   Dates détectées: {prediction['features']['nb_dates']}")
        print(f"   Incertitude: ±{prediction['uncertainty']}s")
    
    elif args.simulate:
        print("🔄 Simulation de données d'entraînement...")
        
        # Simuler quelques extractions pour entraîner le modèle
        simulations = [
            # (text_size, nb_products, nb_dates, file_type, actual_time)
            ("A" * 2000, "pdf", 45.0),   # Petit PDF, rapide
            ("A" * 3500, "pdf", 65.0),   # PDF moyen
            ("A" * 5000, "pdf", 95.0),   # Grand PDF
            ("A" * 1500, "html", 25.0),  # HTML léger
            ("A" * 3000, "txt", 35.0),   # TXT moyen
        ]
        
        for text, ftype, actual in simulations:
            # Ajouter des codes produits fictifs
            nb_prods = int(len(text) / 200)
            text_with_prods = text + "\n".join([f"\n{str(10000+i)}\n" for i in range(nb_prods)])
            
            predictor.update(text_with_prods, ftype, actual)
        
        print(f"✅ {len(simulations)} simulations enregistrées")
        stats = predictor.get_stats()
        print(f"📊 Erreur moyenne: {stats['mean_error']}s")
    
    else:
        parser.print_help()
