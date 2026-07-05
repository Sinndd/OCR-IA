"""
Tests unitaires pour JSONComparator (Administration/ocr_evaluate.py).

Ces tests valident la logique de comparaison champ-a-champ utilisee pour
mesurer la precision d'extraction du pipeline OCR, independamment de tout
appel reel a Ollama/LLaVA (aucun modele n'est sollicite ici : on teste la
logique de comparaison sur des dictionnaires synthetiques).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Administration"))
sys.path.insert(0, str(Path(__file__).parent.parent / "Production"))

from ocr_evaluate import JSONComparator


def test_identical_dicts_full_precision():
    comparator = JSONComparator()
    expected = {"numCommande": "01142-32721-1", "client": "NEWREST"}
    actual = {"numCommande": "01142-32721-1", "client": "NEWREST"}

    comparator.compare_dicts(expected, actual)

    assert comparator.get_precision() == 100.0
    assert comparator.stats["errors"] == []


def test_value_mismatch_is_recorded_as_error():
    comparator = JSONComparator()
    expected = {"numCommande": "01142-32721-1"}
    actual = {"numCommande": "01142-32721-2"}

    comparator.compare_dicts(expected, actual)

    assert comparator.get_precision() == 0.0
    assert len(comparator.stats["errors"]) == 1
    assert comparator.stats["errors"][0]["path"] == "numCommande"


def test_missing_key_counts_as_error():
    comparator = JSONComparator()
    expected = {"numCommande": "123", "client": "API"}
    actual = {"numCommande": "123"}

    comparator.compare_dicts(expected, actual)

    assert comparator.stats["total_fields"] == 2
    assert comparator.stats["correct_fields"] == 1
    missing = [e for e in comparator.stats["errors"] if e["actual"] == "MISSING"]
    assert len(missing) == 1
    assert missing[0]["path"] == "client"


def test_string_comparison_is_case_and_whitespace_insensitive():
    comparator = JSONComparator()
    expected = {"client": "  NewRest  "}
    actual = {"client": "newrest"}

    comparator.compare_dicts(expected, actual)

    assert comparator.get_precision() == 100.0


def test_nested_dict_comparison():
    comparator = JSONComparator()
    expected = {"livraison": {"date": "2026-07-01", "agence": "SUD CHAPONNAY"}}
    actual = {"livraison": {"date": "2026-07-01", "agence": "AUTRE AGENCE"}}

    comparator.compare_dicts(expected, actual)

    assert comparator.stats["total_fields"] == 2
    assert comparator.stats["correct_fields"] == 1
    assert comparator.stats["errors"][0]["path"] == "livraison.agence"


def test_list_length_mismatch_is_recorded():
    comparator = JSONComparator()
    expected = {"produits": [{"code": "A1"}, {"code": "A2"}]}
    actual = {"produits": [{"code": "A1"}]}

    comparator.compare_dicts(expected, actual)

    length_errors = [e for e in comparator.stats["errors"] if e["path"] == "produits.length"]
    assert len(length_errors) == 1
    assert length_errors[0]["expected"] == 2
    assert length_errors[0]["actual"] == 1


def test_precision_is_zero_when_no_fields_compared():
    comparator = JSONComparator()
    assert comparator.get_precision() == 0.0


def test_empty_string_expected_vs_none_actual_is_a_mismatch():
    """
    Documente un comportement reel (et non intuitif) de _normalize_value :
    une chaine vide "" et None ne sont PAS consideres equivalents, car la
    branche `isinstance(value, str)` est evaluee avant la branche
    `value is None or value == ""`. Ce test fige ce comportement actuel
    plutot que d'en supposer un autre.
    """
    comparator = JSONComparator()
    expected = {"commentaire": ""}
    actual = {"commentaire": None}

    comparator.compare_dicts(expected, actual)

    assert comparator.get_precision() == 0.0


def test_none_expected_and_none_actual_are_equivalent():
    comparator = JSONComparator()
    expected = {"commentaire": None}
    actual = {"commentaire": None}

    comparator.compare_dicts(expected, actual)

    assert comparator.get_precision() == 100.0
