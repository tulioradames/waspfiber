#!/bin/bash
# Assistente do Servidor WaspFiber: cadastra uma empresa (com o dominio de
# e-mail dela) e o primeiro usuario - normalmente o administrador, que depois
# aprova pelo programa os pedidos de "Criar conta" da equipe.
#   bash ~/waspfiber-servidor/criar-acesso.sh
S="$HOME/waspfiber-servidor/waspfiber_servidor.py"
D="$HOME/waspfiber-dados"
echo
echo "== WaspFiber: cadastrar empresa e usuario =="
echo
read -r -p "Nome da empresa (ex.: Zaaz NE): " NOME
ID=$(python3 -c "import sys; sys.path.insert(0, '$HOME/waspfiber-servidor'); import waspfiber_servidor as w; print(w.slug(sys.argv[1]))" "$NOME")
if [ -z "$ID" ]; then echo "Nome invalido."; exit 1; fi
if [ -f "$D/empresas/$ID/empresa.json" ]; then
  echo "A empresa ja existe ($ID)."
else
  python3 "$S" criar-empresa --dados "$D" "$ID" "$NOME" || exit 1
fi
read -r -p "Dominio do e-mail da empresa (ex.: zaaztelecom.com.br): " DOMINIO
if [ -n "$DOMINIO" ]; then
  python3 "$S" definir-dominio --dados "$D" "$ID" "$DOMINIO" || exit 1
fi
read -r -p "E-mail do usuario (ex.: fulano@$DOMINIO): " EMAIL
read -r -p "Nome da pessoa: " PESSOA
read -r -p "Administrador (aprova os pedidos de acesso)? (s/n): " ADM
EXTRA=""
if [ "$ADM" = "s" ] || [ "$ADM" = "S" ]; then EXTRA="--admin"; fi
python3 "$S" criar-usuario --dados "$D" "$ID" "$EMAIL" "$PESSOA" $EXTRA || exit 1
echo
echo "Pronto. No WaspFiber, entre com o e-mail $EMAIL e a senha."
echo "A equipe pode usar 'Criar conta' com e-mail @$DOMINIO; o administrador aprova no programa."
echo
