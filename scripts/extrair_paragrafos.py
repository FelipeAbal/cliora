#!/usr/bin/env python3
"""
Extrai pares (Surya, embutido) por bloco para alimentar o LLM de correção.
Salva em JSON estruturado para inspeção e reuso.
"""
import json, re, sys
import fitz  # pymupdf

PDF_PATH     = "input/Teste.pdf"
RESULTS_PATH = "output/surya/Teste/results.json"
OUTPUT_PATH  = "checkpoints/pagina_{n}_payload.json"

def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', text).strip()

def extrair_surya(results_path):
    with open(results_path) as f:
        data = json.load(f)
    pages = list(data.values())[0]
    resultado = []
    for i, page in enumerate(pages):
        blocos = []
        for b in page['blocks']:
            if b['label'] in ('Text', 'SectionHeader', 'Footnote'):
                blocos.append({
                    'label': b['label'],
                    'texto': strip_html(b['html'])
                })
        resultado.append(blocos)
    return resultado

def extrair_embutido(pdf_path):
    doc = fitz.open(pdf_path)
    resultado = []
    for page in doc:
        texto = page.get_text("text")
        # limpa artefatos tipicos do OCR embutido
        texto = re.sub(r'\n{3,}', '\n\n', texto)
        resultado.append(texto.strip())
    return resultado

import os
os.makedirs("checkpoints", exist_ok=True)

surya_pages  = extrair_surya(RESULTS_PATH)
embut_pages  = extrair_embutido(PDF_PATH)

for i, (surya_blocos, embut_texto) in enumerate(zip(surya_pages, embut_pages)):
    payload = {
        "pagina": i + 1,
        "surya_blocos": surya_blocos,
        "embutido_raw": embut_texto
    }
    path = OUTPUT_PATH.format(n=i+1)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    n_blocos = len(surya_blocos)
    n_words_emb = len(embut_texto.split())
    n_words_sur = sum(len(b['texto'].split()) for b in surya_blocos)
    print(f"Página {i+1}: {n_blocos} blocos Surya | "
          f"{n_words_sur} palavras Surya | "
          f"{n_words_emb} palavras embutido → {path}")

print("\nPayloads salvos em checkpoints/")
