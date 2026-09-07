import time
import json
import os
import re
from google import genai
from pypdf import PdfReader

# ==========================================
# CONFIGURAÇÕES - RESGATE ECONÔMICO E SEGURO
# ==========================================
MINHA_API_KEY = os.environ["GEMINI_API_KEY"]
NOME_DO_PDF = "livro1.pdf"  
ARQUIVO_JSON_RESGATE = "resgate_paginas.json"

PAGINAS_PARA_RESGATAR = [
    57, 58, 59, 61, 62, 123, 124, 125, 128, 133, 135, 136, 142, 180, 181, 185, 186, 
    239, 241, 242, 244, 245, 246, 247, 248, 249, 252, 254, 260, 261, 301, 302, 305, 
    337, 357, 369, 370, 371, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 
    383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 
    399, 400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 
    415, 416, 417, 418, 419, 420, 421, 422, 423, 424, 425
]

client = genai.Client(api_key=MINHA_API_KEY)
reader = PdfReader(NOME_DO_PDF)

def limpar_texto(texto):
    # Purga caracteres de controle invisíveis que quebram APIs
    texto_limpo = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', texto)
    return "".join(ch for ch in texto_limpo if ch.isprintable() or ch in '\n\r\t')

livro_resgatado = []
if os.path.exists(ARQUIVO_JSON_RESGATE):
    try:
        with open(ARQUIVO_JSON_RESGATE, "r", encoding="utf-8") as f:
            livro_resgatado = json.load(f).get("livro", [])
    except:
        pass

paginas_feitas = {p.get("numero_pagina") for p in livro_resgatado}

prompt_instrucoes = (
    "Você deve ler o texto de uma página de um livro jurídico antigo organizado em duas colunas.\n"
    "Sua missão é reorganizar o texto na ordem correta de leitura vertical (coluna 1 completa, depois coluna 2).\n"
    "Preserve a ortografia original da época.\n\n"
    "Formate sua resposta estritamente usando tags estruturadas em formato de texto comum, exatamente assim:\n"
    "PARAGRAFO: [Número ou Identificador do Parágrafo]\n"
    "TEXTO: [Conteúdo integral do parágrafo]\n"
    "NOTA: [Conteúdo das notas laterais ou de rodapé, se houver]\n"
    "---"
)

print(f"🛡️ Modo de Segurança Ativado! Processando sem custo adicional.")

for num_pagina in PAGINAS_PARA_RESGATAR:
    if num_pagina in paginas_feitas:
        continue
        
    print(f"⚡ Processando texto purificado da página {num_pagina}...")
    texto_cru = reader.pages[num_pagina - 1].extract_text()
    texto_pagina = limpar_texto(texto_cru)
    
    if not texto_pagina.strip():
        continue
        
    try:
        # Forçamos o uso da requisição simples sem schema pesado para economizar e não travar
        resposta = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt_instrucoes, f"Texto bruto da página {num_pagina}:\n{texto_pagina}"]
        )
        
        texto_resposta = respuesta.text
        blocos_conteudo = []
        paragrafos = texto_resposta.split("---")
        
        for p in paragrafos:
            linhas = p.strip().split("\n")
            num_p, txt_p, n_p = "Geral", "", ""
            for linha in linhas:
                if linha.startswith("PARAGRAFO:"): num_p = linha.replace("PARAGRAFO:", "").strip()
                elif linha.startswith("TEXTO:"): txt_p = linha.replace("TEXTO:", "").strip()
                elif linha.startswith("NOTA:"): n_p = linha.replace("NOTA:", "").strip()
            if txt_p:
                blocos_conteudo.append({
                    "numero_paragrafo": num_p,
                    "texto_paragrafo": txt_p,
                    "notas_laterais_ou_rodape": n_p
                })
        
        livro_resgatado.append({
            "numero_pagina": num_pagina,
            "conteudo": blocks_conteudo if 'blocks_conteudo' in locals() else blocos_conteudo
        })
        
        print(f"✅ Página {num_pagina} estruturada localmente com sucesso!")
        with open(ARQUIVO_JSON_RESGATE, "w", encoding="utf-8") as f_saida:
            json.dump({"livro": livro_resgatado}, f_saida, ensure_ascii=False, indent=2)
            
        time.sleep(6) # Pausa técnica para respeitar a cota de RPM gratuita
        
    except Exception as e:
        print(f"⚠️ Aguardando cota para a página {num_pagina}...")
        time.sleep(15)

print(f"\n🎉 Fim do resgate seguro. Arquivo salvo: {ARQUIVO_JSON_RESGATE}")
