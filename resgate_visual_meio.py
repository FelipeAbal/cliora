import time
import json
import os
from google import genai
from google.genai import types
from pdf2image import convert_from_path

# ==========================================
# CONFIGURAÇÕES - RESGATE VISUAL ECONOMICO
# ==========================================
MINHA_API_KEY = os.environ["GEMINI_API_KEY"]
NOME_DO_PDF = "livro1.pdf"  
ARQUIVO_JSON_RESGATE = "resgate_paginas_meio.json"

# Apenas as páginas do meio do livro que falharam (antes do índice)
PAGINAS_MEIO = [
    57, 58, 59, 61, 62, 123, 124, 125, 128, 133, 135, 136, 142, 180, 181, 185, 186, 
    239, 241, 242, 244, 245, 246, 247, 248, 249, 252, 254, 260, 261, 301, 302, 305, 
    337, 357
]
# ==========================================

client = genai.Client(api_key=MINHA_API_KEY)

livro_resgatado = []
if os.path.exists(ARQUIVO_JSON_RESGATE):
    try:
        with open(ARQUIVO_JSON_RESGATE, "r", encoding="utf-8") as f:
            livro_resgatado = json.load(f).get("livro", [])
    except:
        pass

paginas_feitas = {p.get("numero_pagina") for p in livro_resgatado}

prompt_instrucoes = (
    "Você é um especialista em transcrição e análise de documentos jurídicos antigos.\n"
    "Analise visualmente a imagem desta página que possui duas colunas de texto.\n"
    "Transcreva o conteúdo organizando as colunas na sequência correta de leitura vertical (coluna 1, depois coluna 2).\n"
    "Preserve a ortografia antiga, corrija quebras de palavras causadas por hifens.\n\n"
    "Responda ESTRITAMENTE com o JSON estruturado abaixo, sem nenhum outro texto:\n"
    "{\n"
    "  \"numero_pagina\": X,\n"
    "  \"conteudo\": [\n"
    "    {\n"
    "      \"numero_paragrafo\": \"Título ou Seção correspondente\",\n"
    "      \"texto_paragrafo\": \"Texto completo do parágrafo\",\n"
    "      \"notas_laterais_ou_rodape\": \"Notas marginais ou notas de rodapé\"\n"
    "    }\n"
    "  ]\n"
    "}\n"
)

print(f"📸 Iniciando conversão e resgate visual de {len(PAGINAS_MEIO)} páginas do meio...")

for num_pagina in PAGINAS_MEIO:
    if num_pagina in paginas_feitas:
        continue
        
    print(f"👁️ Convertendo e lendo visualmente a página {num_pagina}...")
    
    try:
        # Converte APENAS a página específica do PDF em imagem (gasto de memória local zero)
        imagens = convert_from_path(NOME_DO_PDF, first_page=num_pagina, last_page=num_pagina)
        if not imagens:
            print(f"❌ Falha ao renderizar imagem da página {num_pagina}")
            continue
            
        # Salva temporariamente em formato JPEG leve
        img_temp = f"temp_pag_{num_pagina}.jpg"
        imagens[0].save(img_temp, "JPEG")
        
        # Faz o upload da imagem leve (apenas alguns kilobytes, consumo mínimo de créditos)
        file_ref = client.files.upload(file=img_temp)
        
        resposta = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[file_ref, prompt_instrucoes],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        texto_limpo = resposta.text.strip().strip("```json").strip("```")
        dados_pagina = json.loads(texto_limpo)
        dados_pagina["numero_pagina"] = num_pagina
        
        livro_resgatado.append(dados_pagina)
        print(f"✅ Página {num_pagina} integrada visualmente com sucesso!")
        
        with open(ARQUIVO_JSON_RESGATE, "w", encoding="utf-8") as f_saida:
            json.dump({"livro": livro_resgatado}, f_saida, ensure_ascii=False, indent=2)
            
        # Limpeza local e remota imediata
        client.files.delete(name=file_ref.name)
        if os.path.exists(img_temp):
            os.remove(img_temp)
            
        time.sleep(2) # Pausa leve de estabilidade
        
    except Exception as e:
        print(f"⚠️ Erro ao processar visualmente a página {num_pagina}: {e}")
        time.sleep(5)

print(f"\n🎉 Resgate visual das páginas do meio concluído! Arquivo: {ARQUIVO_JSON_RESGATE}")
