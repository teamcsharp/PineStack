(() => {
  const api = window.stationTroubleshooter, results = document.getElementById('results'), status = document.getElementById('status');
  const labels = { checked: 'Checked', verified: 'Verified', attention: 'Needs attention', failed: 'Failed', changed: 'Changed', running: 'In progress', looked: 'Checked', proved: 'Verified' };
  function paint(state) {
    const follow = results.scrollTop + results.clientHeight >= results.scrollHeight - 40;
    status.textContent = state.title;
    document.querySelectorAll('button[data-action]').forEach(button => { button.disabled = state.busy; });
    results.replaceChildren();
    for (const entry of [...(state.entries || []), ...(state.busy ? state.audioSteps || [] : [])]) {
      const card = document.createElement('article'), title = document.createElement('h2'), badge = document.createElement('span'), detail = document.createElement('pre');
      card.dataset.status = entry.status || entry.state; title.textContent = entry.label; badge.textContent = labels[card.dataset.status] || card.dataset.status;
      title.appendChild(badge); detail.textContent = entry.detail || ''; card.append(title, detail); results.appendChild(card);
    }
    if (follow) results.scrollTop = results.scrollHeight;
  }
  document.querySelectorAll('button[data-action]').forEach(button => button.addEventListener('click', async () => {
    document.querySelectorAll('button[data-action]').forEach(control => { control.disabled = true; });
    try { paint(await api.run(button.dataset.action)); }
    catch (error) { status.textContent = error.message; document.querySelectorAll('button[data-action]').forEach(control => { control.disabled = false; }); }
  }));
  api.onState(paint); api.state().then(paint).catch(error => { status.textContent = error.message; });
})();
