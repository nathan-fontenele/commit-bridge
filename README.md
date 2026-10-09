# Azure DevOps Activity Sync

Automação em Python que registra, em um repositório GitHub **privado**, os commits feitos no Azure DevOps por e-mails de autoria configurados. Ela consulta todos os projetos, repositórios e branches acessíveis, cria uma linha Markdown para cada commit novo e publica **um commit Git no destino por atividade encontrada**. Dias sem atividade não geram arquivos ou commits artificiais.

O repositório com este código executa o GitHub Actions. Um segundo repositório, separado e privado, guarda os dados:

```text
commit-bridge/                 # código, configuração modelo e workflow
daily-activity/                # exemplo de destino privado
├── activity/2026/10/2026-10-08.md
└── state/synced_commits.json
```

Cada linha do arquivo diário tem o formato `[projeto] primeira linha da mensagem - abcdef12`. A data do arquivo é a data da **sincronização em America/Sao_Paulo**; o estado evita duplicatas entre branches e execuções. Os commits do GitHub usam a data real em que são criados.

## Requisitos

- Python 3.12 ou superior e Git para execução local.
- Acesso de leitura aos projetos e repositórios relevantes no Azure DevOps.
- Um repositório GitHub para este código e outro **privado** para as atividades.
- Autorização da sua organização para exportar nomes de projetos, mensagens e hashes de commits para uma conta GitHub pessoal.

## 1. Faça um fork e clone o código

Se você quer executar a automação na sua conta, use **Fork** na página deste repositório no GitHub. O fork será o repositório que executará o workflow. Depois clone **o seu fork**:

```bash
git clone https://github.com/SEU_USUARIO/commit-bridge.git
cd commit-bridge
```

Se você já possui uma cópia do projeto na sua conta, basta cloná-la; não precisa fazer outro fork. Um clone local, sozinho, não cria um workflow na sua conta GitHub. A disponibilidade do botão **Fork** para repositórios privados depende das permissões do proprietário.

## 2. Crie o repositório privado de destino

No GitHub, crie um **novo repositório privado** para as atividades, por exemplo `SEU_USUARIO/daily-activity`. Inicialize-o com um README para que tenha uma branch padrão e um commit inicial. Os arquivos `activity/` e `state/` serão criados pela automação nesse repositório, não no fork do código. O workflow interrompe a execução se o destino não for privado.

## 3. Crie os tokens de acesso

1. No Azure DevOps, acesse **User settings → Personal access tokens → New Token**. Selecione a organização correta, uma validade curta e somente **Project and Team (read)** e **Code (read)**. Copie o PAT ao criá-lo. [Instruções da Microsoft](https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate?view=azure-devops).
2. No GitHub, acesse **Settings → Developer settings → Personal access tokens → Fine-grained tokens**. Escolha seu usuário como proprietário, selecione **somente o repositório de destino** e conceda **Contents: Read and write**. A permissão **Metadata: Read** é automática. Copie o token ao criá-lo. [Instruções do GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

O `GITHUB_TOKEN` do workflow pertence ao repositório do código e não substitui o token para acessar um [segundo repositório privado](https://github.com/actions/checkout).

## 4. Configure o seu fork no GitHub

No **fork do código**, abra **Settings → Secrets and variables → Actions**. Cadastre os valores abaixo em **Repository secrets**; `SYNC_GIT_NAME` deve ser criado na aba **Variables**. Nenhum token deve ser escrito em `config.yaml` ou enviado em um commit. [Como cadastrar secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

| Tipo | Nome | Valor de exemplo |
| --- | --- | --- |
| Secret | `AZURE_DEVOPS_PAT` | PAT do Azure DevOps criado no passo 3 |
| Secret | `AZURE_DEVOPS_ORGANIZATION` | `minha-organizacao`, de `dev.azure.com/minha-organizacao` |
| Secret | `AZURE_AUTHOR_EMAILS` | `eu@empresa.com` ou vários e-mails separados por vírgula |
| Secret | `ACTIVITY_REPOSITORY` | `SEU_USUARIO/daily-activity` |
| Secret | `ACTIVITY_REPOSITORY_TOKEN` | Token GitHub criado no passo 3 |
| Secret | `SYNC_GIT_EMAIL` | E-mail associado à sua conta GitHub |
| Variable | `SYNC_GIT_NAME` | Nome que assinará os commits no destino |

O `config.yaml` versionado é um modelo seguro para publicação. Com as listas `include: []`, a busca cobre todos os projetos, repositórios e branches acessíveis ao PAT; use `include` e `exclude` para restringir nomes quando necessário. No Actions, a organização e os e-mails vêm dos secrets e substituem os exemplos do arquivo.

## 5. Teste e ative a sincronização

1. Garanta que o workflow esteja na **branch padrão do seu fork** e que o GitHub Actions esteja habilitado. Em forks de repositórios públicos, workflows agendados [começam desabilitados](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows?tool=webui); habilite o workflow antes de esperar a execução automática.
2. No fork, abra **Actions → Sync Azure DevOps activity → Run workflow**, marque `dry_run: true` e execute. Isso testa autenticação e descoberta sem publicar. Por segurança, os logs do Actions não exibem nomes, mensagens, SHAs do Azure nem contagens de atividade.
3. Para conferir **quais** commits seriam publicados, use a prévia local descrita abaixo em um ambiente privado. Depois execute o workflow com `dry_run: false` e confira o repositório de destino. Se não houver commit novo, ele não será modificado.

O agendamento roda a cada hora, no minuto 17 UTC. A consulta normal cobre os últimos sete dias. Na execução manual, o campo `since` aceita `YYYY-MM-DD` em UTC para reprocessar um período mais antigo sem duplicar os commits já registrados.

### Prévia local detalhada

Clone também o repositório privado de destino, como uma pasta irmã do projeto. Crie uma cópia local da configuração e edite nela a organização e os e-mails:

```bash
git clone https://github.com/SEU_USUARIO/daily-activity.git ../daily-activity
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp config.yaml config.local.yaml
# Edite config.local.yaml; esse arquivo é ignorado pelo Git.
export AZURE_DEVOPS_PAT='SEU_PAT_AZURE'
python -m src.main --config config.local.yaml --destination ../daily-activity --dry-run --show-details
```

O modo `--show-details` exibe metadados corporativos no terminal; não o use em um CI público. Uma publicação local também exige `GITHUB_COMMIT_EMAIL`, `GITHUB_COMMIT_NAME`, `GITHUB_DEFAULT_BRANCH` e acesso de push ao remoto do destino.

## Como a sincronização evita duplicatas

O cliente usa a API REST 7.1 do Azure DevOps para listar projetos, repositórios, branches e commits, com paginação e retries. O filtro compara `author.email`; a ordenação usa `committer.date`. A chave `organização:repositório:SHA` elimina repetição entre branches. A cada atividade nova, o publicador adiciona a linha Markdown e a chave no estado **no mesmo commit Git**; se o push falhar, consulta novamente o estado remoto antes de tentar outra vez.

Commits presentes apenas em branches apagadas antes da busca não são encontrados. Execuções agendadas podem [atrasar ou ser descartadas](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows); use `since` quando o atraso exceder a janela padrão. O gráfico do GitHub segue suas [regras de atribuição de contribuições](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference), inclusive associação do e-mail do commit à conta.

## Antes de publicar o código

O repositório de atividades deve permanecer privado. Revise também o histórico Git e as execuções antigas do Actions antes de tornar **o repositório do código** público: [o histórico e os logs do Actions ficam visíveis](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility). `config.local.yaml`, `.env`, tokens e arquivos de atividade não devem entrar no repositório do código.

Para rodar os testes locais:

```bash
python -m unittest discover -s tests -v
```
