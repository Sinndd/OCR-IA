#!/usr/bin/env python3
"""
Fine-tuning LLM pour extraction OCR
Réentraîne un modèle sur tes exemples de bons de commande

Prérequis:
    pip install transformers datasets peft accelerate bitsandbytes torch

Usage:
    python finetune_llm.py --prepare    # Prépare les données d'entraînement
    python finetune_llm.py --train      # Lance le fine-tuning
    python finetune_llm.py --test       # Teste le modèle fine-tuné
"""

import argparse
import json
import os
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

# Configuration
BASE_DIR = Path(__file__).parent.parent
PATTERNS_DIR = BASE_DIR / "patterns"
TRAINING_DATA_DIR = BASE_DIR / "training" / "data"
OUTPUT_MODEL_DIR = BASE_DIR / "training" / "finetuned_model"
TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Modèle de base (peut être changé)
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # ou "mistralai/Mistral-7B-Instruct-v0.2"


class DatasetPreparer:
    """Prépare les données d'entraînement à partir des patterns existants"""
    
    def __init__(self, patterns_dir: Path):
        self.patterns_dir = patterns_dir
    
    def collect_training_pairs(self) -> List[Dict[str, str]]:
        """
        Collecte toutes les paires (texte BC, JSON attendu) depuis les patterns
        """
        pairs = []
        
        for client_dir in self.patterns_dir.glob("CLIENT_*"):
            if not client_dir.is_dir():
                continue
            
            client_id = client_dir.name.replace("CLIENT_", "")
            print(f"📂 Client: {client_id}")
            
            # Chercher les paires BC texte + JSON
            bc_files = list(client_dir.glob("training_bc_*.txt"))
            json_files = list(client_dir.glob("training_json_*.json"))
            
            # Associer par numéro
            for bc_file in bc_files:
                # Extraire le numéro: training_bc_1.txt -> 1
                try:
                    num = bc_file.stem.split("_")[-1]
                    json_file = client_dir / f"training_json_{num}.json"
                    
                    if json_file.exists():
                        with open(bc_file, 'r', encoding='utf-8') as f:
                            bc_text = f.read()
                        with open(json_file, 'r', encoding='utf-8') as f:
                            expected_json = json.load(f)
                        
                        pairs.append({
                            "input": bc_text,
                            "output": json.dumps(expected_json, ensure_ascii=False, indent=2),
                            "client": client_id,
                            "source": str(bc_file)
                        })
                        print(f"  Paire trouvée: {bc_file.name} + {json_file.name}")
                except Exception as e:
                    print(f"  ⚠️ Erreur: {e}")
        
        return pairs
    
    def format_for_training(self, pairs: List[Dict]) -> List[Dict]:
        """
        Formate les paires pour l'entraînement (format instruction-following)
        """
        formatted = []
        
        system_prompt = """Tu es un expert en extraction de données de bons de commande.
Tu reçois le texte brut d'un bon de commande et tu dois extraire les informations structurées en JSON.
Le JSON doit contenir: entete (origine, codeEtablissement, numCommande, dateCommande, dateLivraison, etc.) 
et detailCommande (produits avec numLigne, codeArticle, libelle, quantite).
Réponds UNIQUEMENT avec le JSON, sans explication."""

        for pair in pairs:
            formatted.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extrait les données de ce bon de commande:\n\n{pair['input']}"},
                    {"role": "assistant", "content": pair['output']}
                ],
                "client": pair.get("client", "unknown")
            })
        
        return formatted
    
    def save_training_data(self, formatted_data: List[Dict], output_file: Path):
        """Sauvegarde les données au format JSONL"""
        with open(output_file, 'w', encoding='utf-8') as f:
            for item in formatted_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"💾 Données sauvegardées: {output_file} ({len(formatted_data)} exemples)")


class LLMFineTuner:
    """Fine-tuning du LLM avec LoRA/QLoRA pour efficacité mémoire"""
    
    def __init__(self, base_model: str, output_dir: Path):
        self.base_model = base_model
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def train(self, training_file: Path, epochs: int = 3, batch_size: int = 1):
        """
        Lance le fine-tuning avec QLoRA (quantifié pour GPU limité)
        """
        try:
            from transformers import (
                AutoModelForCausalLM, 
                AutoTokenizer, 
                TrainingArguments,
                Trainer,
                DataCollatorForLanguageModeling
            )
            from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
            from datasets import load_dataset
            import torch
        except ImportError as e:
            print(f"Dépendances manquantes: {e}")
            print("Installez: pip install transformers datasets peft accelerate bitsandbytes torch")
            return False
        
        print(f"\n{'='*60}")
        print(f"🚀 FINE-TUNING LLM")
        print(f"📦 Modèle de base: {self.base_model}")
        print(f"📚 Données: {training_file}")
        print(f"💾 Sortie: {self.output_dir}")
        print(f"{'='*60}\n")
        
        # Charger le tokenizer
        print("🔧 Chargement du tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(self.base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        
        # Charger le modèle en 4-bit pour économiser la mémoire
        print("🔧 Chargement du modèle (quantifié 4-bit)...")
        try:
            from transformers import BitsAndBytesConfig
            
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True
            )
            
            model = AutoModelForCausalLM.from_pretrained(
                self.base_model,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True
            )
        except Exception as e:
            print(f"⚠️ Quantification 4-bit non disponible, chargement standard...")
            model = AutoModelForCausalLM.from_pretrained(
                self.base_model,
                device_map="auto",
                trust_remote_code=True,
                torch_dtype=torch.float16
            )
        
        # Préparer pour l'entraînement
        model = prepare_model_for_kbit_training(model)
        
        # Configuration LoRA
        print("🔧 Configuration LoRA...")
        lora_config = LoraConfig(
            r=16,  # Rank
            lora_alpha=32,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM"
        )
        
        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()
        
        # Charger les données
        print("📚 Chargement des données d'entraînement...")
        dataset = load_dataset('json', data_files=str(training_file), split='train')
        
        def tokenize_function(examples):
            # Formater en prompt complet
            texts = []
            for messages in examples['messages']:
                text = ""
                for msg in messages:
                    if msg['role'] == 'system':
                        text += f"<|system|>\n{msg['content']}\n"
                    elif msg['role'] == 'user':
                        text += f"<|user|>\n{msg['content']}\n"
                    elif msg['role'] == 'assistant':
                        text += f"<|assistant|>\n{msg['content']}\n"
                texts.append(text)
            
            return tokenizer(
                texts,
                truncation=True,
                max_length=2048,
                padding="max_length"
            )
        
        tokenized_dataset = dataset.map(tokenize_function, batched=True, remove_columns=dataset.column_names)
        
        # Arguments d'entraînement
        training_args = TrainingArguments(
            output_dir=str(self.output_dir / "checkpoints"),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=4,
            warmup_steps=10,
            learning_rate=2e-4,
            fp16=True,
            logging_steps=10,
            save_steps=100,
            save_total_limit=2,
            optim="paged_adamw_8bit",
            report_to="none"
        )
        
        # Trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized_dataset,
            data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
        )
        
        # Entraînement
        print("\n🎯 Démarrage de l'entraînement...")
        trainer.train()
        
        # Sauvegarder
        print("\n💾 Sauvegarde du modèle fine-tuné...")
        model.save_pretrained(self.output_dir / "lora_adapter")
        tokenizer.save_pretrained(self.output_dir / "tokenizer")
        
        # Sauvegarder les métadonnées
        metadata = {
            "base_model": self.base_model,
            "training_file": str(training_file),
            "epochs": epochs,
            "date": datetime.now().isoformat()
        }
        with open(self.output_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"\nFine-tuning terminé!")
        print(f"📂 Modèle sauvegardé dans: {self.output_dir}")
        return True


class FineTunedInference:
    """Utilise le modèle fine-tuné pour l'extraction"""
    
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.model = None
        self.tokenizer = None
    
    def load(self):
        """Charge le modèle fine-tuné"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel
            import torch
        except ImportError as e:
            print(f"Dépendances manquantes: {e}")
            return False
        
        # Charger les métadonnées
        metadata_file = self.model_dir / "metadata.json"
        if not metadata_file.exists():
            print(f"Métadonnées introuvables: {metadata_file}")
            return False
        
        with open(metadata_file) as f:
            metadata = json.load(f)
        
        base_model = metadata["base_model"]
        
        print(f"🔧 Chargement du modèle fine-tuné...")
        print(f"  Base: {base_model}")
        
        # Charger le tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_dir / "tokenizer",
            trust_remote_code=True
        )
        
        # Charger le modèle de base
        base = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.float16
        )
        
        # Appliquer l'adaptateur LoRA
        self.model = PeftModel.from_pretrained(base, self.model_dir / "lora_adapter")
        self.model.eval()
        
        print("Modèle chargé!")
        return True
    
    def extract(self, text: str) -> Dict:
        """Extrait les données d'un texte de BC"""
        if not self.model or not self.tokenizer:
            print("Modèle non chargé")
            return {}
        
        import torch
        
        system_prompt = """Tu es un expert en extraction de données de bons de commande.
Tu reçois le texte brut d'un bon de commande et tu dois extraire les informations structurées en JSON.
Le JSON doit contenir: entete (origine, codeEtablissement, numCommande, dateCommande, dateLivraison, etc.) 
et detailCommande (produits avec numLigne, codeArticle, libelle, quantite).
Réponds UNIQUEMENT avec le JSON, sans explication."""

        prompt = f"<|system|>\n{system_prompt}\n<|user|>\nExtrait les données de ce bon de commande:\n\n{text}\n<|assistant|>\n"
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=2048,
                temperature=0.1,
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id
            )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Extraire le JSON de la réponse
        try:
            # Chercher le JSON dans la réponse
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ Erreur parsing JSON: {e}")
        
        return {}


def main():
    parser = argparse.ArgumentParser(description="Fine-tuning LLM pour extraction OCR")
    parser.add_argument('--prepare', action='store_true', help='Prépare les données d\'entraînement')
    parser.add_argument('--train', action='store_true', help='Lance le fine-tuning')
    parser.add_argument('--test', action='store_true', help='Teste le modèle fine-tuné')
    parser.add_argument('--epochs', type=int, default=3, help='Nombre d\'epochs')
    parser.add_argument('--model', type=str, default=BASE_MODEL, help='Modèle de base')
    
    args = parser.parse_args()
    
    if args.prepare:
        print("\n📊 PRÉPARATION DES DONNÉES D'ENTRAÎNEMENT\n")
        preparer = DatasetPreparer(PATTERNS_DIR)
        pairs = preparer.collect_training_pairs()
        
        if not pairs:
            print("Aucune paire d'entraînement trouvée!")
            print("💡 Ajoutez des fichiers training_bc_N.txt et training_json_N.json dans les dossiers patterns/CLIENT_*/")
            return
        
        formatted = preparer.format_for_training(pairs)
        output_file = TRAINING_DATA_DIR / "training_data.jsonl"
        preparer.save_training_data(formatted, output_file)
        
        print(f"\n{len(formatted)} exemples préparés")
        print(f"📂 Fichier: {output_file}")
        print(f"\n💡 Lancez maintenant: python finetune_llm.py --train")
    
    elif args.train:
        training_file = TRAINING_DATA_DIR / "training_data.jsonl"
        if not training_file.exists():
            print("Données d'entraînement introuvables!")
            print("💡 Lancez d'abord: python finetune_llm.py --prepare")
            return
        
        finetuner = LLMFineTuner(args.model, OUTPUT_MODEL_DIR)
        finetuner.train(training_file, epochs=args.epochs)
    
    elif args.test:
        if not (OUTPUT_MODEL_DIR / "metadata.json").exists():
            print("Modèle fine-tuné introuvable!")
            print("💡 Lancez d'abord: python finetune_llm.py --train")
            return
        
        inference = FineTunedInference(OUTPUT_MODEL_DIR)
        if not inference.load():
            return
        
        # Test avec un exemple
        test_text = """
        BON DE COMMANDE
        Client: SODEXO
        N° 12345
        Date: 15/01/2026
        
        Code    Désignation         Qté
        ABC123  Produit Test 1      10
        DEF456  Produit Test 2      5
        """
        
        print("\n📝 Test d'extraction:")
        print(test_text)
        print("\n📤 Résultat:")
        result = inference.extract(test_text)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
