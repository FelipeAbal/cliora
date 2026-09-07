import time
import json
import os
from google import genai
from google.genai import types
from pypdf import PdfReader

# ==========================================
# CONFIGURAÇÕES - OPERAÇÃO RESGATE PAGO
# ==========================================
MINHA_API_KEY = os.environ["GEMINI_API_KEY"]
NOME_DO_PDF = "livro1.pdf"  
ARQUIVO_JSON_RESGATE = "resgate_paginas.json"

# Lista exata gerada pela sua varredura
PAGINAS_PARA_RESGATAR = [
    57, 58, 59, 61, 62, 123, 124, 125, 128, 133, 135, 136, 142, 180, 181, 185, 186, 
    239, 241, 242, 244, 245, 246, 247, 248, 249, 252, 254, 260, 261, 301, 302, 305, 
    337, 357, 369, 370, 371, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 
    383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 
    399, 400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 
    415, 416, 417, 418, 419, 420, 421, 422, 423, 424, 425
]
# ==========================================

client = genai.Client(api_key=MINHA_API_KEY)
reader = PdfReader(NOME_DO_PDF)

livro_resgatado = []
if os.path.exists(ARQUIVO_JSON_RESGATE):
    try:
        with open(ARQUIVO_JSON_RESGATE, "r", encoding="utf-8") as f:
            livro_resgatado = json.load(f).get("livro", [])
    except:
        pass

paginas_feitas = {p.get("numero_pagina") for p in livro_resgatado}

prompt_instrucoes = (
    "Você é um especialista em estruturação de dados históricos.\n"
    "Sua tarefa é ler o texto bagunçado de um PDF de duas colunas antigas e organizá-lo em formato JSON válido.\n\n"
    "Garante a ordem correta de leitura vertical das colunas. Corrija palavras quebradas mantendo a ortografia arcaica.\n\n"
    "Sua resposta deve conter UNICAMENTE o bloco JSON estruturado, sem blocos de texto explicativos adicionais antes ou depois.\n\n"
    "Estrutura esperada do JSON:\n"
    "{\n"
    "  \"numero_pagina\": X,\n"
    "  \"conteudo\": [\n"
    "    {\n"
    "      \"numero_paragrafo\": \"Número ou Nome da Seção\",\n"
    "      \"texto_paragrafo\": \"Texto completo do parágrafo aqui...\",\n"
    "      \"notas_laterais_ou_rodape\": \"Notas se houverem\"\n"
    "    }\n"
    "  ]\n"
    "}\n"
)

print(f"🚁 Operação Resgate Iniciada! {len(PAGINAS_PARA_RESGATAR)} páginas na mira.")

for num_pagina in PAGINAS_PARA_RESGATAR:
    if num_pagina in paginas_feitas:
        continue
        
    print(f"⚡ Resgatando página {num_pagina}...")
    texto_pagina = reader.pages[num_pagina - 1].extract_text()
    
    if not texto_pagina.strip():
        print(f"📭 Página {num_pagina} sem texto extraível.")
        continue
        
    tentativas = 0
    sucesso = False
    
    while tentativas < 3 and not sucesso:
        try:
            resposta = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt_instrucoes, f"Texto da página {num_pagina}:\n{texto_pagina}"],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                ),
            )
            
            # Limpa possíveis blocos de marcação de markdown se a IA colocar por engano
            texto_limpo = resposta.text.strip().strip("```json").strip("```")
            dados_pagina = json.loads(texto_limpo)
            
            # Força o número da página correto caso o modelo se confunda no JSON interno
            dados_pagina["numero_pagina"] = num_pagina
            
            livro_resgatado.append(dados_pagina)
            print(f"✅ Página {num_pagina} salva no arquivo de resgate!")
            
            with open(ARQUIVO_JSON_RESGATE, "w", encoding="utf-8") as f_saida:
                json.dump({"livro": libro_resgatado}, f_saida, ensure_ascii=False, indent=2)
                
            sucesso = True
            
        except Exception as e:
            tentativas += 1
            print(f"⚠️ Erro no resgate da página {num_pagina}. Tentativa {tentativas}/3. Aguardando 4s...")
            time.sleep(4)
            
    if sucesso:
        time.sleep(0.5)
    else:
        print(f"❌ Falha definitiva na página {num_pagina} nesta rodada.")

print(f"\n🎉 Fim do resgate! Verifique o arquivo temporário: {ARQUIVO_JSON_RESGATE}")
