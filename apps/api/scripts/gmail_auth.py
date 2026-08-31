"""Autorização OAuth do Gmail em dois passos, sem servidor de callback.

    python scripts/gmail_auth.py url
        imprime a URL de autorização. Abra no navegador, autorize, e copie a URL
        para a qual o navegador for redirecionado (vai dar "não é possível acessar
        o site" — normal; o que importa é o ?code=... na barra de endereço).

    python scripts/gmail_auth.py token "<url colada>"
        troca o código pelo token e grava token.json.

O estado de PKCE entre os dois passos fica em /tmp/gmail_auth_state.json.
"""

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

RAIZ = Path(__file__).resolve().parents[3]
ESCOPOS = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT = "http://localhost:8765/"
ESTADO = Path("/tmp/gmail_auth_state.json")


def _flow() -> InstalledAppFlow:
    cred = RAIZ / "credentials.json"
    if not cred.exists():
        sys.exit(f"credentials.json não encontrado em {cred}")
    flow = InstalledAppFlow.from_client_secrets_file(str(cred), ESCOPOS)
    flow.redirect_uri = REDIRECT
    return flow


def gerar_url() -> None:
    flow = _flow()
    url, estado = flow.authorization_url(access_type="offline", prompt="consent")
    ESTADO.write_text(json.dumps({"code_verifier": flow.code_verifier, "state": estado}))
    print(url)


def trocar_token(resposta: str) -> None:
    if not ESTADO.exists():
        sys.exit("rode primeiro: python scripts/gmail_auth.py url")
    salvo = json.loads(ESTADO.read_text())
    flow = _flow()
    flow.code_verifier = salvo["code_verifier"]

    resposta = resposta.strip()
    if resposta.startswith("http"):
        flow.fetch_token(authorization_response=resposta)
    else:
        flow.fetch_token(code=resposta)  # cola só o valor de code=

    (RAIZ / "token.json").write_text(flow.credentials.to_json())
    ESTADO.unlink(missing_ok=True)
    print(f"OK — token salvo em {RAIZ / 'token.json'}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "url":
        gerar_url()
    elif len(sys.argv) >= 3 and sys.argv[1] == "token":
        trocar_token(sys.argv[2])
    else:
        sys.exit(__doc__)
