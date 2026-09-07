import time
import json
import os
from google import genai
from google.genai import types
from pypdf import PdfReader

# ==========================================
# CONFIGURAÇÕES - MODO PRODUÇÃO (PLANO PAGO)
# ==========================================
MINHA_API_KEY = os.environ["GEMINI_API_KEY"]
NOME_DO_PDF = "livro1.pdf"  
ARQUIVO_JSON_SAIDA = "transcricao_estruturada.json"
# ==========================================

client = genai.Client(api_key=MINHA_API_KEY)
reader = PdfReader(NOME_DO_PDF)
total_paginas = len(reader.pages)
print(f"📄 PDF carregado com sucesso! Total: {total_paginas} páginas.")

livro_completo = []
paginas_ja_processadas = set()

# Recupera o progresso anterior
if os.path.exists(ARQUIVO_JSON_SAIDA):
    try:
        with open(ARQUIVO_JSON_SAIDA, "r", encoding="utf-8") as f_leitura:
            dados_existentes = json.load(f_leitura)
            livro_completo = dados_existentes.get("livro", [])
            for p in livro_completo:
                # Evita salvar páginas marcadas com erro anteriormente para refazê-las agora com o plano pago
                if p.get("conteudo") and p["conteudo"][0].get("numero_paragrafo") != "ERRO":
                    paginas_ja_processadas.add(p.get("numero_pagina"))
        print(f"💾 Progresso recuperado: {len(paginas_ja_processadas)} páginas já estruturadas com sucesso.")
    except Exception:
        print("⚠️ Falha ao ler histórico. Iniciando limpo.")

prompt_instrucoes = (
    "Você vai receber um texto extraído de um PDF antigo de duas colunas. Esse texto está zoneado, "
    "com palavras cortadas ou colunas misturadas horizontalmente. Sua missão é reconstruir esse texto "
    "organizá-lo estritamente no formato JSON estruturado.\n\n"
    "REGRAS CRÍTICAS:\n"
    "1. Reordene a leitura vertical correta de cada coluna.\n"
    "2. Corrija palavras quebradas, mas mantenha rigorosamente a ortografia da época.\n"
    "3. Não omita numerações de seções ou notas.\n"
)

esquema_json = {
    "type": "OBJECT",
    "properties": {
        "paginas": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "numero_pagina": {"type": "INTEGER"},
                    "conteudo": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "numero_paragrafo": {"type": "STRING"},
                                "texto_paragrafo": {"type": "STRING"},
                                "notes_laterais_ou_rodape": {"type": "STRING"}
                            },
                            "required": ["numero_paragrafo", "texto_paragrafo", "notes_laterais_ou_rodape"]
                        }
                    }
                },
                "required": ["numero_pagina", "conteudo"]
            }
        }
    },
    "required": ["paginas"]
}

for i in range(24, total_paginas):
    num_pagina_real = i + 1
    
    if num_pagina_real in paginas_ja_processadas:
        continue
        
    print(f"⏳ Processando página {num_pagina_real}/{total_paginas}...")
    texto_pagina = reader.pages[i].extract_text()
    
    if not texto_pagina.strip():
        print(f"📭 Página {num_pagina_real} vazia, pulando...")
        continue
        
    texto_bloco = f"\n--- INÍCIO DA PÁGINA {num_pagina_real} ---\n{texto_pagina}\n--- FIM DA PÁGINA {num_pagina_real} ---\n"
    
    tentativas = 0
    sucesso = False
    
    while tentativas < 3 and not sucesso:
        try:
            resposta = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt_instrucoes, f"Aqui está o texto bagunçado da página:\n{texto_bloco}"],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=esquema_json,
                    temperature=0.1
                ),
            )
            
            dados_bloco = json.loads(resposta.text)
            livro_completo.append(dados_bloco.get("paginas", [{}])[0])
            print(f"✅ Página {num_pagina_real} processada e salva com sucesso!")
            
            with open(ARQUIVO_JSON_SAIDA, "w", encoding="utf-8") as f_saida:
                json.dump({"livro": livro_completo}, f_saida, ensure_ascii=False, indent=2)
            
            sucesso = True
            
        except Exception as e:
            tentativas += 1
            print(f"⚠️ Instabilidade temporária na página {num_pagina_real}. Tentativa {tentativas}/3. Aguardando 5s...")
            time.sleep(5)
            
    if sucesso:
        time.sleep(1) # Pausa mínima de 1 segundo (só para não sobrecarregar sua rede local)
    else:
        print(f"❌ Não foi possível obter resposta para a página {num_pagina_real} após 3 tentativas.")

print(f"\n🎉 Processo concluído! Verifique o arquivo final: {ARQUIVO_JSON_SAIDA}")
