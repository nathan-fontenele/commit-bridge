# Azure DevOps Activity Sync

Sincroniza commits reais do Azure DevOps para este repositório GitHub privado. Cada commit novo encontrado produz um commit Git com uma linha em `activity/YYYY/MM/YYYY-MM-DD.md` e sua chave em `state/synced_commits.json`. A data do arquivo é a data da publicação em `America/Sao_Paulo`.

## Preparação

1. Confirme que a política da empresa permite copiar nomes de projetos, mensagens e hashes para sua conta pessoal. Mantenha este repositório **privado**.
2. Edite `config.yaml`: informe o nome da organização e todos os e-mails de autoria. As listas `include` vazias significam todos os recursos acessíveis; `exclude` remove nomes específicos. Branches são filtradas pelo nome sem `refs/heads/`.
3. Crie um PAT do Azure DevOps com **Project and Team (read)** e **Code (read)**, limitado aos projetos necessários e com expiração curta. Salve-o no secret `AZURE_DEVOPS_PAT` deste repositório GitHub.
4. Cadastre no secret `GITHUB_COMMIT_EMAIL` um e-mail verificado na conta GitHub que deve receber as contribuições. Configure a variável `GITHUB_COMMIT_NAME` com o nome do autor. O workflow usa o `GITHUB_TOKEN` com `contents: write` e publica na branch padrão. Se ela estiver protegida, permita o push do workflow ou ajuste a regra.
5. Faça commit e push dos arquivos para a branch padrão. O agendamento executa a cada hora, no minuto 17 UTC. Também é possível iniciar em **Actions → Sync Azure DevOps activity → Run workflow**.

## Prévia e recuperação

Na execução manual, marque `dry_run` para ver os commits candidatos no log sem escrever arquivos ou publicar commits. As mensagens aparecerão nesse log; limite o acesso aos logs a quem pode ver esses metadados.

O campo manual `since` aceita uma data UTC `YYYY-MM-DD` para reprocessamento histórico. Sem esse campo, a busca usa os últimos sete dias. Commits antigos fora dessa janela exigem um backfill manual. O estado impede republicação de commits já registrados, inclusive quando aparecem em mais de uma branch.

Para executar localmente:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export AZURE_DEVOPS_PAT='...'
python -m src.main --dry-run
python -m unittest discover -s tests -v
```

Uma publicação local também requer `GITHUB_COMMIT_EMAIL`, `GITHUB_COMMIT_NAME`, `GITHUB_DEFAULT_BRANCH` e acesso de push ao remoto `origin`. Execute em um checkout limpo: o publicador sincroniza o checkout com `origin/<branch>` antes de gravar. O workflow atende a essas condições automaticamente.

## Garantias e limites

- Os commits são filtrados pelo `author.email` e ordenados pelo `committer.date`. A busca cobre as branches acessíveis configuradas, com paginação; a chave `organização:repositório:SHA` remove repetições entre branches.
- A linha e o estado são gravados no mesmo commit Git. Após uma resposta incerta do push, o publicador busca o estado remoto antes de tentar novamente. Nenhum arquivo é criado quando não há atividade nova.
- O repositório precisa estar privado e o e-mail de autoria associado à conta GitHub. O GitHub aplica suas próprias [regras de atribuição de contribuições](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference); a aparição no gráfico não é garantida pelo script. A opção de exibir contribuições privadas no perfil é controlada na conta GitHub.
- Commits que existam apenas em branches apagadas antes da sincronização não são encontrados. O agendamento do GitHub Actions pode [atrasar ou perder execuções](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows); use `since` para recuperar intervalos maiores que a janela padrão.

Referências: [projetos](https://learn.microsoft.com/en-us/rest/api/azure/devops/core/projects/list?view=azure-devops-rest-7.1), [repositórios](https://learn.microsoft.com/en-us/rest/api/azure/devops/git/repositories/list?view=azure-devops-rest-7.1), [refs](https://learn.microsoft.com/en-us/rest/api/azure/devops/git/refs/list?view=azure-devops-rest-7.1), [commits](https://learn.microsoft.com/en-us/rest/api/azure/devops/git/commits/get-commits?view=azure-devops-rest-7.1).
