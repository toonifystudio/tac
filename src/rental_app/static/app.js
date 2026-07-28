const API_BASE = '/api';

async function fetchApplications() {
  const resp = await fetch(`${API_BASE}/applications`);
  return resp.json();
}

function renderApps(apps) {
  const tbody = document.getElementById('appsTbody');
  tbody.innerHTML = '';
  const filter = document.getElementById('stateFilter').value;
  apps.filter(a => !filter || a.state === filter).forEach(a => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><a href="#" data-id="${a.id}" class="app-link">${a.id}</a></td>
                    <td>${a.message_id}</td>
                    <td>${new Date(a.created_at).toLocaleString()}</td>
                    <td>${a.state}</td>
                    <td>${a.missing_documents ? a.missing_documents.join(', ') : ''}</td>
                    <td>${a.last_error || ''}</td>`;
    tbody.appendChild(tr);
  });
  document.querySelectorAll('.app-link').forEach(el => el.addEventListener('click', async (e) => {
    e.preventDefault();
    const id = e.target.dataset.id;
    await loadDetail(id);
  }));
}

async function loadList() {
  try {
    const apps = await fetchApplications();
    // For each application, we will fetch detail missing_documents lazily in detail view.
    renderApps(apps);
  } catch (err) {
    console.error('Failed to load applications', err);
  }
}

async function loadDetail(id) {
  const el = document.getElementById('detailContent');
  el.innerHTML = 'Loading...';
  try {
    const resp = await fetch(`${API_BASE}/applications/${id}`);
    if (!resp.ok) {
      el.innerText = 'Failed to load application details';
      return;
    }
    const data = await resp.json();
    el.innerHTML = '';
    const header = document.createElement('div');
    header.innerHTML = `<h3>Application ${data.id}</h3>
                        <p><strong>Message ID:</strong> ${data.message_id}</p>
                        <p><strong>State:</strong> ${data.state}</p>
                        <p><strong>Missing:</strong> ${data.missing_documents.join(', ')}</p>
                        <p><strong>Last error:</strong> ${data.last_error || ''}</p>`;
    el.appendChild(header);

    const docsSection = document.createElement('section');
    docsSection.innerHTML = '<h4>Documents</h4>';
    const ul = document.createElement('ul');
    data.documents.forEach(d => {
      const li = document.createElement('li');
      li.innerHTML = `<strong>${d.filename}</strong> — ${d.document_type || 'unknown'}<br/><small>OCR snippet: ${d.ocr_text ? d.ocr_text.slice(0,200) : ''}</small>`;
      docsSection.appendChild(li);
    });
    el.appendChild(docsSection);

    const pkgSection = document.createElement('section');
    pkgSection.innerHTML = '<h4>Packages</h4>';
    data.packages.forEach(p => {
      const a = document.createElement('a');
      a.href = `/api/packages/${p.id}/file`;
      a.innerText = `Download package ${p.id}`;
      a.target = '_blank';
      pkgSection.appendChild(a);
    });
    el.appendChild(pkgSection);

    const notesSection = document.createElement('section');
    notesSection.innerHTML = '<h4>Reviewer Notes</h4>';
    const notesList = document.createElement('ul');
    data.notes.forEach(n => {
      const li = document.createElement('li');
      li.innerHTML = `<strong>${n.reviewer || 'Reviewer'}</strong>: ${n.note} <small>(${new Date(n.created_at).toLocaleString()})</small>`;
      notesList.appendChild(li);
    });
    notesSection.appendChild(notesList);
    const noteForm = document.createElement('div');
    noteForm.innerHTML = `<input id="noteReviewer" placeholder="your name"/> <br/><textarea id="noteText" placeholder="Add a note"></textarea><br/><button id="addNote">Add Note</button>`;
    notesSection.appendChild(noteForm);
    el.appendChild(notesSection);

    document.getElementById('addNote').addEventListener('click', async () => {
      const reviewer = document.getElementById('noteReviewer').value;
      const note = document.getElementById('noteText').value;
      if (!note) return alert('Note is required');
      await fetch(`${API_BASE}/applications/${data.id}/notes`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({reviewer, note})});
      await loadDetail(id);
      await loadList();
    });

    const actions = document.createElement('div');
    actions.innerHTML = `<button id="approveBtn">Approve (send draft)</button> <button id="rejectBtn">Reject</button>`;
    el.appendChild(actions);

    document.getElementById('approveBtn').addEventListener('click', async () => {
      if (!confirm('Approve this application and send the Gmail draft? This will send the draft to the configured recipient.')) return;
      const resp = await fetch(`${API_BASE}/applications/${data.id}/approve`, {method:'POST'});
      if (resp.ok) {
        alert('Approved and draft sent');
        await loadDetail(id);
        await loadList();
      } else {
        const json = await resp.json();
        alert('Failed to approve: ' + JSON.stringify(json));
      }
    });

    document.getElementById('rejectBtn').addEventListener('click', async () => {
      const reason = prompt('Reject reason (optional)');
      const resp = await fetch(`${API_BASE}/applications/${data.id}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({reason})});
      if (resp.ok) {
        alert('Rejected');
        await loadDetail(id);
        await loadList();
      } else {
        alert('Failed to reject');
      }
    });

  } catch (err) {
    console.error('Failed to load detail', err);
  }
}

window.addEventListener('load', () => {
  document.getElementById('refreshBtn').addEventListener('click', loadList);
  document.getElementById('stateFilter').addEventListener('change', loadList);
  loadList();
});
