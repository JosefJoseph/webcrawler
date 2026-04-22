import json
import os
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse
import pandas as pd
from fpdf import FPDF


CSV_WIDE_COLUMNS = [
    'source_url',
    'path',
    'page_title',
    'food_name',
    'product_name',
    'food_id',
    'fdc_id',
    'page_id',
    'brand',
    'manufacturer',
    'category',
    'subcategory',
    'food_class',
    'data_type',
    'description',
    'ingredients',
    'allergens',
    'serving_size',
    'serving_unit',
    'household_serving',
    'package_size',
    'calories',
    'protein',
    'fat',
    'saturated_fat',
    'carbohydrates',
    'sugar',
    'fiber',
    'sodium',
    'cholesterol',
    'vitamins',
    'minerals',
    'portion_description',
    'country',
    'language',
    'published_at',
    'updated_at',
    'keyword_matches',
    'matched_block_count',
    'match_occurrence_count',
    'raw_metadata_json',
    'raw_text',
]

_NUTRIENT_FIELD_MAP = {
    'Energy (Atwater General Factors)': 'calories',
    'Calories': 'calories',
    'Protein': 'protein',
    'Total lipid (fat)': 'fat',
    'Fatty acids, total saturated': 'saturated_fat',
    'Carbohydrate, by difference': 'carbohydrates',
    'Sugars, total including NLEA': 'sugar',
    'Sugars, total': 'sugar',
    'Fiber, total dietary': 'fiber',
    'Sodium, Na': 'sodium',
    'Cholesterol': 'cholesterol',
}

NUTRITION_SUMMARY_KEYS = [
    'calories',
    'protein',
    'fat',
    'saturated_fat',
    'carbohydrates',
    'sugar',
    'fiber',
    'sodium',
    'cholesterol',
    'calcium',
    'iron',
    'magnesium',
    'phosphorus',
    'potassium',
    'zinc',
    'copper',
    'manganese',
    'selenium',
    'vitamin_a',
    'vitamin_b1',
    'vitamin_b2',
    'vitamin_b3',
    'vitamin_b5',
    'vitamin_b6',
    'vitamin_b7',
    'vitamin_b9',
    'vitamin_b12',
    'vitamin_c',
    'vitamin_d',
    'vitamin_e',
    'vitamin_k',
    'water',
    'ash',
    'starch',
    'sugars_total',
    'fructose',
    'glucose',
    'lactose',
    'sucrose',
    'caffeine',
]

_LABEL_TO_FIELD = {
    'brand owner': 'brand',
    'brand': 'brand',
    'manufacturer': 'manufacturer',
    'food category': 'category',
    'category': 'category',
    'subcategory': 'subcategory',
    'food class': 'food_class',
    'data type': 'data_type',
    'description': 'description',
    'ingredients': 'ingredients',
    'allergens': 'allergens',
    'portion': 'portion_description',
    'household serving': 'household_serving',
    'package size': 'package_size',
    'country': 'country',
    'language': 'language',
    'published': 'published_at',
    'updated': 'updated_at',
    'fdc id': 'fdc_id',
    'food id': 'food_id',
    'page id': 'page_id',
}


def _pdf_safe_text(value: Any) -> str:
    """Konvertiert Texte in ein PDF-kompatibles Latin-1-Format."""
    text = str(value)
    return text.encode('latin-1', 'replace').decode('latin-1')


def _empty_wide_record() -> dict[str, str]:
    """Erzeugt einen leeren CSV-Datensatz mit stabilem Wide-Schema."""
    return {column: '' for column in CSV_WIDE_COLUMNS}


def _extract_text_corpus(row: dict[str, Any]) -> str:
    """Fasst relevante Textquellen eines Ergebnisses zu einem Suchkorpus zusammen."""
    parts = []
    title = row.get('title', '')
    if title:
        parts.append(str(title))

    text_value = row.get('text', '')
    if text_value:
        parts.append(str(text_value))

    for block in row.get('matched_blocks', []):
        block_text = block.get('text', '')
        if block_text:
            parts.append(str(block_text))

    for item in row.get('attribute_texts', []):
        item_text = item.get('text', '')
        if item_text:
            parts.append(str(item_text))

    return ' '.join(part.strip() for part in parts if part).strip()


def _extract_with_label(text: str, labels: list[str]) -> str:
    """Extrahiert den Wert nach einem bekannten Label wie `Ingredients:`."""
    for label in labels:
        pattern = re.compile(
            rf'{re.escape(label)}\s*:\s*(.+?)(?=\s+[A-Z][A-Za-z0-9\s\-/()]+\s*:|$)',
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            return match.group(1).strip(' |;,.')
    return ''


def _extract_serving_info(text: str) -> tuple[str, str]:
    """Erkennt Portionsgröße und Einheit aus typischen Food-Textmustern."""
    serving_match = re.search(r'Serving Size\s*:?\s*([<>]?\d+(?:\.\d+)?)\s*([A-Za-zµ]+)', text, re.IGNORECASE)
    if serving_match:
        return serving_match.group(1), serving_match.group(2)

    portion_match = re.search(r'Portion selection\s*:?\s*([<>]?\d+(?:\.\d+)?)\s*([A-Za-zµ]+)', text, re.IGNORECASE)
    if portion_match:
        return portion_match.group(1), portion_match.group(2)

    return '', ''


def _extract_fdc_id(url: str, text: str) -> str:
    """Liest eine FDC-ID aus Text oder URL aus."""
    text_match = re.search(r'FDC\s*ID\s*:?\s*(\d+)', text, re.IGNORECASE)
    if text_match:
        return text_match.group(1)

    url_match = re.search(r'/food-details/(\d+)', url)
    if url_match:
        return url_match.group(1)

    return ''


def _extract_nutrients(text: str) -> list[dict[str, Any]]:
    """Extrahiert Nährstoffeinträge aus Rohtext in normalisierter Zwischenform."""
    nutrient_pattern = re.compile(
        r'([A-Za-z][A-Za-z0-9 ,()\-/%]{1,80}?)\s+([<>]?\d+(?:\.\d+)?)\s*(kcal|kj|g|mg|µg|mcg|IU)',
        re.IGNORECASE,
    )
    nutrients = []
    seen = set()

    for index, match in enumerate(nutrient_pattern.finditer(text), start=1):
        name = match.group(1).strip()
        amount = match.group(2).strip()
        unit = match.group(3).strip()

        if len(name) < 3 or len(name) > 80:
            continue

        key = (name.lower(), amount, unit.lower())
        if key in seen:
            continue
        seen.add(key)

        nutrients.append(
            {
                'nutrient_name': name,
                'nutrient_amount': amount,
                'nutrient_unit': unit,
                'nutrient_id': '',
                'nutrient_rank': index,
            }
        )

    return nutrients


def _extract_key_values(text: str) -> dict[str, str]:
    """Extrahiert generische Key-Value-Paare aus strukturierten Textsegmenten."""
    key_values = {}
    pattern = re.compile(
        r'([A-Z][A-Za-z0-9\s\-/()]{2,40})\s*:\s*(.{1,200}?)(?=\s+[A-Z][A-Za-z0-9\s\-/()]{2,40}\s*:|$)',
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        key = ' '.join(match.group(1).split()).strip().lower()
        value = ' '.join(match.group(2).split()).strip(' |;,.')
        if key and value:
            key_values[key] = value
    return key_values


def normalize_food_record(
    row: dict[str, Any],
    debug_logger: Callable[[str, str], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Normalisiert ein Crawling-Ergebnis in ein stabiles Food-Wide-Datenmodell.

    Args:
        row: Rohes Ergebnisobjekt aus dem Crawl-/Filterprozess.
        debug_logger: Optionale Logging-Callback-Funktion (`level`, `message`).

    Returns:
        Ein Tupel aus Wide-Datensatz, erkannter Nährstoffliste und Zusatzmetadaten.
    """
    record = _empty_wide_record()
    url = str(row.get('url', ''))
    parsed_url = urlparse(url)
    text = _extract_text_corpus(row)
    key_values = _extract_key_values(text)
    nutrients = _extract_nutrients(text)

    record['source_url'] = url
    record['path'] = parsed_url.path or '/'
    record['page_title'] = str(row.get('title', ''))
    record['keyword_matches'] = ', '.join(row.get('keyword_matches', []))
    record['matched_block_count'] = row.get('matched_block_count', 0)
    record['match_occurrence_count'] = row.get('match_occurrence_count', 0)
    record['raw_text'] = text

    record['fdc_id'] = _extract_fdc_id(url, text)
    record['food_id'] = record['fdc_id']
    record['page_id'] = record['fdc_id']

    record['food_name'] = _extract_with_label(text, ['Food Details', 'Food Name'])
    if not record['food_name'] and record['page_title']:
        record['food_name'] = record['page_title'].split('-')[0].strip()
    record['product_name'] = record['food_name']

    record['brand'] = _extract_with_label(text, ['Brand Owner', 'Brand'])
    record['manufacturer'] = _extract_with_label(text, ['Manufacturer'])
    record['category'] = _extract_with_label(text, ['Food Category', 'Category'])
    record['subcategory'] = _extract_with_label(text, ['Subcategory'])
    record['food_class'] = _extract_with_label(text, ['Food Class'])
    record['data_type'] = _extract_with_label(text, ['Data Type'])
    record['description'] = _extract_with_label(text, ['Description'])
    record['ingredients'] = _extract_with_label(text, ['Ingredients'])
    record['allergens'] = _extract_with_label(text, ['Allergens'])
    record['household_serving'] = _extract_with_label(text, ['Household Serving'])
    record['package_size'] = _extract_with_label(text, ['Package Size'])
    record['portion_description'] = _extract_with_label(text, ['Portion'])
    record['country'] = _extract_with_label(text, ['Country'])
    record['language'] = _extract_with_label(text, ['Language'])
    record['published_at'] = _extract_with_label(text, ['Published', 'FDC Published'])
    record['updated_at'] = _extract_with_label(text, ['Updated'])
    record['serving_size'], record['serving_unit'] = _extract_serving_info(text)

    vitamins = []
    minerals = []
    for nutrient in nutrients:
        nutrient_name = nutrient['nutrient_name']
        mapped_field = _NUTRIENT_FIELD_MAP.get(nutrient_name)
        if mapped_field and not record[mapped_field]:
            record[mapped_field] = nutrient['nutrient_amount']
        if any(token in nutrient_name.lower() for token in ['vitamin', 'thiamin', 'niacin', 'folate', 'biotin']):
            vitamins.append(f"{nutrient_name}={nutrient['nutrient_amount']} {nutrient['nutrient_unit']}")
        if any(token in nutrient_name.lower() for token in ['calcium', 'iron', 'magnesium', 'phosphorus', 'potassium', 'sodium', 'zinc', 'copper', 'manganese', 'selenium']):
            minerals.append(f"{nutrient_name}={nutrient['nutrient_amount']} {nutrient['nutrient_unit']}")

    record['vitamins'] = '; '.join(vitamins)
    record['minerals'] = '; '.join(minerals)

    unmapped = {}
    for key, value in key_values.items():
        mapped_field = _LABEL_TO_FIELD.get(key)
        if mapped_field and not record.get(mapped_field):
            record[mapped_field] = value
        elif key not in _LABEL_TO_FIELD:
            unmapped[key] = value

    metadata = {
        'unmapped_fields': unmapped,
        'detected_nutrients': nutrients,
    }
    record['raw_metadata_json'] = json.dumps(metadata, ensure_ascii=False)

    if debug_logger:
        debug_logger('DEBUG', f'Strukturierte Felder extrahiert für {url}: {[key for key, value in record.items() if value and key not in ["raw_text", "raw_metadata_json"]]}')
        debug_logger('DEBUG', f'Erkannte Nährstoffe: {len(nutrients)}')
        debug_logger('DEBUG', f'Nicht gemappte Metadaten-Keys: {list(unmapped.keys())}')

    return record, nutrients, metadata


def build_food_csv_rows(
    rows: list[dict[str, Any]],
    debug_logger: Callable[[str, str], None] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Baut den CSV-Export im Wide-Format aus einer Ergebnisliste auf."""
    wide_rows = []
    food_row_count = 0

    for row in rows:
        structured_record, _, _ = normalize_food_record(row, debug_logger=debug_logger)
        if structured_record.get('fdc_id') or structured_record.get('food_name'):
            food_row_count += 1

        wide_rows.append(structured_record)

    data_frame = pd.DataFrame(wide_rows)
    if data_frame.empty:
        data_frame = pd.DataFrame(columns=CSV_WIDE_COLUMNS)
    else:
        data_frame = data_frame.reindex(columns=CSV_WIDE_COLUMNS)

    stats = {
        'food_row_count': food_row_count,
        'total_input_rows': len(rows),
        'total_output_rows': len(data_frame),
        'layout': 'wide',
    }

    if debug_logger:
        debug_logger('INFO', f'Erkannte Food-Zeilen: {food_row_count}')
        debug_logger('INFO', f'Finale CSV-Zeilenanzahl: {len(data_frame)}')

    return data_frame, stats


def _to_list(value: str) -> list[str]:
    """Zerlegt semistrukturierte Listenwerte in eine bereinigte Python-Liste."""
    if not value:
        return []
    parts = re.split(r'[;,|]', str(value))
    return [part.strip() for part in parts if part.strip()]


def _to_number(value: str) -> float | int | None:
    """Konvertiert einen numerischen Text robust in `int`/`float` oder `None`."""
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    value_str = value_str.replace(',', '.')
    value_str = value_str.replace('<', '').replace('>', '')
    match = re.search(r'\d+(?:\.\d+)?', value_str)
    if not match:
        return None
    number = float(match.group(0))
    if number.is_integer():
        return int(number)
    return number


def map_nutrient_to_normalized_key(nutrient_name: str) -> str | None:
    """Mapped USDA-/FDC-Nährstoffnamen auf stabile Normalisierungs-Keys."""
    name = (nutrient_name or '').strip().lower()
    if not name:
        return None

    direct_map = {
        'energy (atwater general factors)': 'calories',
        'energy': 'calories',
        'calories': 'calories',
        'protein': 'protein',
        'total lipid (fat)': 'fat',
        'fatty acids, total saturated': 'saturated_fat',
        'carbohydrate, by difference': 'carbohydrates',
        'sugars, total including nlea': 'sugars_total',
        'sugars, total': 'sugars_total',
        'fiber, total dietary': 'fiber',
        'sodium, na': 'sodium',
        'cholesterol': 'cholesterol',
        'calcium, ca': 'calcium',
        'iron, fe': 'iron',
        'magnesium, mg': 'magnesium',
        'phosphorus, p': 'phosphorus',
        'potassium, k': 'potassium',
        'zinc, zn': 'zinc',
        'copper, cu': 'copper',
        'manganese, mn': 'manganese',
        'selenium, se': 'selenium',
        'water': 'water',
        'ash': 'ash',
        'starch': 'starch',
        'fructose': 'fructose',
        'glucose': 'glucose',
        'lactose': 'lactose',
        'sucrose': 'sucrose',
        'caffeine': 'caffeine',
        'thiamin': 'vitamin_b1',
        'riboflavin': 'vitamin_b2',
        'niacin': 'vitamin_b3',
        'pantothenic acid': 'vitamin_b5',
        'vitamin b-6': 'vitamin_b6',
        'biotin': 'vitamin_b7',
        'folate, total': 'vitamin_b9',
        'vitamin b-12': 'vitamin_b12',
        'vitamin c, total ascorbic acid': 'vitamin_c',
        'vitamin d (d2 + d3)': 'vitamin_d',
        'vitamin e (alpha-tocopherol)': 'vitamin_e',
        'vitamin k (phylloquinone)': 'vitamin_k',
        'vitamin a, rae': 'vitamin_a',
    }
    if name in direct_map:
        return direct_map[name]

    contains_rules = [
        ('carbohydrate', 'carbohydrates'),
        ('sugar', 'sugars_total'),
        ('fiber', 'fiber'),
        ('sodium', 'sodium'),
        ('cholesterol', 'cholesterol'),
        ('calcium', 'calcium'),
        ('iron', 'iron'),
        ('magnesium', 'magnesium'),
        ('phosphorus', 'phosphorus'),
        ('potassium', 'potassium'),
        ('zinc', 'zinc'),
        ('copper', 'copper'),
        ('manganese', 'manganese'),
        ('selenium', 'selenium'),
        ('vitamin a', 'vitamin_a'),
        ('vitamin c', 'vitamin_c'),
        ('vitamin d', 'vitamin_d'),
        ('vitamin e', 'vitamin_e'),
        ('vitamin k', 'vitamin_k'),
        ('protein', 'protein'),
        ('fat', 'fat'),
        ('caffeine', 'caffeine'),
        ('water', 'water'),
        ('ash', 'ash'),
        ('starch', 'starch'),
        ('fructose', 'fructose'),
        ('glucose', 'glucose'),
        ('lactose', 'lactose'),
        ('sucrose', 'sucrose'),
    ]
    for token, normalized in contains_rules:
        if token in name:
            return normalized

    return None


def _extract_ingredient_list(value: str) -> list[str]:
    """Extrahiert die Zutatenliste als Array."""
    return _to_list(value)


def _extract_allergen_list(value: str) -> list[str]:
    """Extrahiert Allergenangaben als Array."""
    return _to_list(value)


def normalize_food_record_for_nosql(
    row: dict[str, Any],
    include_raw_text: bool = False,
    debug_logger: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Erstellt ein NoSQL-freundliches Dokument pro Food-/Produktseite."""
    structured_record, nutrients, metadata = normalize_food_record(row, debug_logger=debug_logger)
    source_url = structured_record.get('source_url', '')
    parsed_url = urlparse(source_url)

    summary = {key: None for key in NUTRITION_SUMMARY_KEYS}
    nutrient_docs = []
    vitamins = []
    minerals = []
    other_nutrients = []

    for nutrient in nutrients:
        nutrient_name = nutrient.get('nutrient_name', '')
        normalized_key = map_nutrient_to_normalized_key(nutrient_name)
        amount = _to_number(nutrient.get('nutrient_amount'))
        nutrient_doc = {
            'name': nutrient_name,
            'normalized_key': normalized_key,
            'amount': amount,
            'unit': nutrient.get('nutrient_unit', ''),
            'id': nutrient.get('nutrient_id') or None,
            'rank': nutrient.get('nutrient_rank') or None,
        }
        nutrient_docs.append(nutrient_doc)

        if normalized_key in summary and summary[normalized_key] is None:
            summary[normalized_key] = amount
            if debug_logger:
                debug_logger('DEBUG', f'Nährstoff zur Summary hinzugefügt: {normalized_key}={amount}')

        if normalized_key and normalized_key.startswith('vitamin_'):
            vitamins.append(nutrient_doc)
        elif normalized_key in {'calcium', 'iron', 'magnesium', 'phosphorus', 'potassium', 'zinc', 'copper', 'manganese', 'selenium', 'sodium'}:
            minerals.append(nutrient_doc)
        else:
            other_nutrients.append(nutrient_doc)

        if debug_logger:
            debug_logger('DEBUG', f'Nährstoff-Mapping: {nutrient_name} -> {normalized_key}')
            debug_logger('DEBUG', f'Nährstoff ins Array übernommen: {nutrient_name}')

    if summary.get('sugar') is None and summary.get('sugars_total') is not None:
        summary['sugar'] = summary.get('sugars_total')

    ingredients = _extract_ingredient_list(structured_record.get('ingredients', ''))
    allergens = _extract_allergen_list(structured_record.get('allergens', ''))
    if debug_logger:
        debug_logger('DEBUG', f'Erkannte Zutaten-Einträge: {len(ingredients)}')
        debug_logger('DEBUG', f'Erkannte Allergen-Einträge: {len(allergens)}')

    document = {
        'source_url': source_url,
        'path': structured_record.get('path', ''),
        'page_title': structured_record.get('page_title', ''),
        'source': {
            'domain': parsed_url.netloc,
            'crawler_version': 'webcrawler-ui-1.1',
            'fetched_at': None,
            'language': structured_record.get('language', ''),
            'country': structured_record.get('country', ''),
        },
        'food': {
            'id': structured_record.get('food_id') or structured_record.get('fdc_id', ''),
            'fdc_id': structured_record.get('fdc_id', ''),
            'name': structured_record.get('food_name', ''),
            'product_name': structured_record.get('product_name', ''),
            'brand': structured_record.get('brand', ''),
            'manufacturer': structured_record.get('manufacturer', ''),
            'category': structured_record.get('category', ''),
            'subcategory': structured_record.get('subcategory', ''),
            'food_class': structured_record.get('food_class', ''),
            'data_type': structured_record.get('data_type', ''),
            'description': structured_record.get('description', ''),
            'ingredients': ingredients,
            'allergens': allergens,
        },
        'serving': {
            'serving_size': _to_number(structured_record.get('serving_size')),
            'serving_unit': structured_record.get('serving_unit', ''),
            'household_serving': structured_record.get('household_serving', ''),
            'package_size': structured_record.get('package_size', ''),
            'portion_description': structured_record.get('portion_description', ''),
        },
        'nutrition': {
            'summary': summary,
            'nutrients': nutrient_docs,
            'vitamins': vitamins,
            'minerals': minerals,
            'other_nutrients': other_nutrients,
        },
        'meta': {
            'published_at': structured_record.get('published_at', ''),
            'updated_at': structured_record.get('updated_at', ''),
            'raw_metadata': metadata,
            'unmapped_fields': metadata.get('unmapped_fields', {}),
            'keyword_matches': _to_list(structured_record.get('keyword_matches', '')),
            'matched_block_count': structured_record.get('matched_block_count', 0),
            'match_occurrence_count': structured_record.get('match_occurrence_count', 0),
        },
    }

    if include_raw_text:
        document['meta']['raw_text'] = structured_record.get('raw_text', '')

    return document


def build_food_json_records(
    rows: list[dict[str, Any]],
    include_raw_text: bool = False,
    debug_logger: Callable[[str, str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Baut JSON-Dokumente für den Export aus der aktuellen Ergebnisliste auf."""
    json_records = []
    food_page_count = 0
    mapped_nutrient_keys = set()

    for row in rows:
        json_record = normalize_food_record_for_nosql(
            row,
            include_raw_text=include_raw_text,
            debug_logger=debug_logger,
        )
        json_records.append(json_record)

        food = json_record.get('food', {})
        if food.get('fdc_id') or food.get('name'):
            food_page_count += 1

        summary = json_record.get('nutrition', {}).get('summary', {})
        for key, value in summary.items():
            if value is not None:
                mapped_nutrient_keys.add(key)

        if debug_logger:
            debug_logger('DEBUG', f'Strukturierte JSON-Felder für {json_record.get("source_url", "")}: {list(json_record.keys())}')
            debug_logger('DEBUG', f'Gemappte Standard-Nährstoffe: {[key for key, value in summary.items() if value is not None]}')
            debug_logger('DEBUG', f'Erkannte Nährstoff-Einträge gesamt: {len(json_record.get("nutrition", {}).get("nutrients", []))}')
            debug_logger('DEBUG', f'Nicht gemappte Metadaten-Keys für {json_record.get("source_url", "")}: {list(json_record.get("meta", {}).get("unmapped_fields", {}).keys())}')

    stats = {
        'food_page_count': food_page_count,
        'total_input_rows': len(rows),
        'total_output_records': len(json_records),
        'mapped_nutrient_keys': sorted(mapped_nutrient_keys),
    }

    if debug_logger:
        debug_logger('INFO', f'Food-Seiten für JSON-Export erkannt: {food_page_count}')
        debug_logger('INFO', f'Finale JSON-Dokumentanzahl: {len(json_records)}')

    return json_records, stats

def generate_filename(base_name: str, domain: str, format_ext: str) -> str:
    """Erzeugt einen stabilen Export-Dateinamen mit Domain und Zeitstempel."""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    safe_domain = domain.replace('https://', '').replace('http://', '').replace('/', '_').replace('.', '_')
    return f"exports/{base_name}_{safe_domain}_{timestamp}.{format_ext}"

def export_to_json(results: pd.DataFrame | list[dict[str, Any]], domain: str) -> str:
    """Schreibt Ergebnisse als JSON-Datei ins Export-Verzeichnis."""
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'json')

    if isinstance(results, pd.DataFrame):
        payload = results.to_dict(orient='records')
    elif isinstance(results, list):
        payload = results
    else:
        payload = []

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
    return filename

def export_to_csv(results_df: pd.DataFrame, domain: str) -> str:
    """Schreibt Ergebnisse im CSV-Wide-Format."""
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'csv')
    results_df.to_csv(filename, index=False, encoding='utf-8')
    return filename

def export_to_pdf(results_df: pd.DataFrame, domain: str) -> str:
    """Schreibt Ergebnisse als PDF-Bericht."""
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'pdf')
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, txt=_pdf_safe_text(f"Crawl Results for {domain}"), ln=True)
    pdf.ln(4)
    for _, row in results_df.iterrows():
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 6, txt=_pdf_safe_text(str(row.to_dict())))
        pdf.multi_cell(0, 6, txt=_pdf_safe_text("---"))
        pdf.ln(1)
    pdf.output(filename)
    return filename

def export_to_markdown(results_df: pd.DataFrame, domain: str) -> str:
    """Schreibt Ergebnisse als Markdown-Tabelle."""
    os.makedirs('exports', exist_ok=True)
    filename = generate_filename('crawl_results', domain, 'md')
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"# Crawl Results for {domain}\n\n")
        f.write(results_df.to_markdown(index=False))
    return filename