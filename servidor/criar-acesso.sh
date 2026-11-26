#!/bin/bash
# Assistente do Servidor WaspFiber: cria a empresa (se ainda nao existir) e
# um usuario dela. A senha e digitada aqui, no terminal do servidor.
#   bash ~/waspfiber-servidor/criar-acesso.sh
S="$HOME/waspfiber-servidor/waspfiber_servidor.py"
D="$HOME/waspfiber-dados"
echo
echo "== WaspFiber: criar acesso =="
echo
read -r -p "Nome da empresa (ex.: Junior Telecom): " NOME
ID=$(python3 -c "import sys; sys.path.insert(0, '$HOME/waspfiber-servidor'); import waspfiber_servidor as w; print(w.slug(sys.argv[1]))" "$NOME")
if [ -z "$ID" ]; then echo "Nome invalido."; exit 1; fi
if [ -f "$D/empresas/$ID/empresa.json" ]; then
  echo "A empresa ja existe (no programa, campo Empresa: $ID)"
else
  python3 "$S" criar-empresa --dados "$D" "$ID" "$NOME" || exit 1
fi
read -r -p "Login do usuario (ex.: tulio): " LOGIN
read -r -p "Nome da pessoa (ex.: Tulio): " PESSOA
read -r -p "Administrador? (s/n): " ADM
EXTRA=""
[ "$ADM" = "s" ] || [ "$ADM" = "S" ] && EXTRA="--admin"
python3 "$S" criar-usuario --dados "$D" "$ID" "$LOGIN" "$PESSOA" $EXTRA || exit 1
echo
echo "Pronto. No WaspFiber use:"
echo "  Servidor: http://$(hostname -I | awk '{print $1}'):8765"
echo "  Empresa:  $ID"
echo "  Usuario:  $LOGIN"
echo
