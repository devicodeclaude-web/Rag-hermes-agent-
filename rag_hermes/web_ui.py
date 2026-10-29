INDEX_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RAG Hermes — V1 locale</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #0b1020; color: #edf2ff; }
    main { width: min(760px, calc(100% - 24px)); margin: 0 auto; padding: 24px 0 48px; }
    h1 { font-size: clamp(1.6rem, 6vw, 2.4rem); margin-bottom: 6px; }
    .lead { color: #aebbd6; margin-top: 0; }
    section { background: #151d32; border: 1px solid #293653; border-radius: 16px; padding: 18px; margin-top: 16px; }
    label { display: block; margin-top: 12px; font-weight: 650; }
    input, textarea, button { box-sizing: border-box; width: 100%; font: inherit; border-radius: 10px; }
    input, textarea { margin-top: 6px; padding: 12px; color: #f7f9ff; background: #0d1426; border: 1px solid #3b4c70; }
    textarea { min-height: 130px; resize: vertical; }
    button { margin-top: 16px; padding: 13px; border: 0; background: #6d7cff; color: white; font-weight: 750; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .status { min-height: 24px; color: #9fd2ff; white-space: pre-wrap; }
    .answer { line-height: 1.55; white-space: pre-wrap; }
    .citation { padding: 12px; margin-top: 10px; background: #0d1426; border-left: 3px solid #6d7cff; overflow-wrap: anywhere; }
    .warning { color: #ffd27d; font-size: .92rem; }
    @media (max-width: 560px) { .grid { grid-template-columns: 1fr; } section { padding: 14px; } }
  </style>
</head>
<body>
<main>
  <h1>RAG Hermes</h1>
  <p class="lead">Importez un texte, puis posez une question. Les réponses restent liées aux sources autorisées.</p>
  <p class="warning">V1 locale : l'identité (tenant, utilisateur, groupes, niveau d'accès) est dérivée côté serveur du jeton ci-dessous, jamais saisie dans la requête. En production, ce jeton sera délivré par le fournisseur d'identité.</p>

  <section aria-labelledby="token-title">
    <h2 id="token-title">Jeton d'accès</h2>
    <label>Jeton porteur (Authorization: Bearer …)<input id="token" type="password" autocomplete="off" placeholder="collez votre jeton"></label>
  </section>

  <section aria-labelledby="document-title">
    <h2 id="document-title">1. Importer un document</h2>
    <form id="document-form">
      <label>Identifiant<input id="document-id" required value="guide-local"></label>
      <label>Source<input id="source-uri" required value="local://guide-local"></label>
      <label>Contenu<textarea id="document-content" required placeholder="Collez ici votre documentation…"></textarea></label>
      <button type="submit">Importer</button>
    </form>
    <p id="document-status" class="status" role="status"></p>
  </section>

  <section aria-labelledby="question-title">
    <h2 id="question-title">2. Poser une question</h2>
    <form id="question-form">
      <label>Question<textarea id="question" required placeholder="Comment installer Hermes ?"></textarea></label>
      <button type="submit">Rechercher une réponse</button>
    </form>
    <p id="question-status" class="status" role="status"></p>
    <div id="answer" class="answer"></div>
    <div id="citations"></div>
  </section>
</main>
<script src="/app.js"></script>
</body>
</html>
"""

APP_JS = """\
'use strict';
(() => {
  const byId = (id) => document.getElementById(id);
  const authHeaders = () => {
    const token = byId('token').value.trim();
    const headers = {'Content-Type': 'application/json'};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return headers;
  };
  async function post(path, payload) {
    const response = await fetch(path, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) throw new Error('Jeton manquant ou invalide.');
      throw new Error(data.error || 'Erreur HTTP');
    }
    return data;
  }
  byId('document-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    byId('document-status').textContent = 'Import en cours…';
    try {
      // tenant_id et owner_id ne sont PAS envoyés : le serveur les dérive du jeton.
      const result = await post('/api/documents', {
        document: {
          document_id: byId('document-id').value.trim(),
          content: byId('document-content').value,
          visibility: 'private',
          allowed_groups: [],
          allowed_users: [],
          classification: 0,
          doc_version: 1,
          source_uri: byId('source-uri').value.trim()
        }
      });
      byId('document-status').textContent = `Document importé : ${result.chunk_count} segment(s).`;
    } catch (error) {
      byId('document-status').textContent = `Échec : ${error.message}`;
    } finally { button.disabled = false; }
  });
  byId('question-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    byId('question-status').textContent = 'Recherche en cours…';
    byId('answer').textContent = '';
    byId('citations').replaceChildren();
    try {
      const result = await post('/api/questions', {
        question: byId('question').value
      });
      byId('question-status').textContent = result.abstained ? 'Abstention : preuve insuffisante.' : 'Réponse fondée sur la source ci-dessous.';
      byId('answer').textContent = result.answer;
      for (const citation of result.citations) {
        const box = document.createElement('div');
        box.className = 'citation';
        const title = document.createElement('strong');
        title.textContent = `${citation.document_id} — ${citation.source_uri}`;
        const quote = document.createElement('p');
        quote.textContent = citation.quote;
        box.append(title, quote);
        byId('citations').append(box);
      }
    } catch (error) {
      byId('question-status').textContent = `Échec : ${error.message}`;
    } finally { button.disabled = false; }
  });
})();
"""
