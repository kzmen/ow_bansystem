(() => {
  const code = window.ROOM_CODE;
  const hostKey = `owban:${code}:host`;
  const playerKey = `owban:${code}:player`;
  const hostToken = () => localStorage.getItem(hostKey) || '';
  const playerToken = () => localStorage.getItem(playerKey) || '';

  let state = null;
  let selected = [];
  let activeRole = 'All';
  let searchText = '';
  let settingsTimer = null;
  let refreshPromise = null;
  let refreshQueued = false;
  let lastRealtimeEvent = 0;

  const $ = (id) => document.getElementById(id);
  const globalError = $('global-error');

  function headers(extra = {}) {
    return {
      'Content-Type': 'application/json',
      'X-Host-Token': hostToken(),
      'X-Player-Token': playerToken(),
      ...extra,
    };
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: headers(options.headers || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || '通信に失敗しました。');
    return data;
  }

  function showError(message) {
    globalError.textContent = message;
    globalError.hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function clearError() {
    globalError.hidden = true;
  }

  async function refresh() {
    if (refreshPromise) {
      refreshQueued = true;
      return refreshPromise;
    }

    refreshPromise = (async () => {
      try {
        const data = await api(`/api/rooms/${code}/state?_=${Date.now()}`);
        state = data;
        clearError();
        if (data.me) selected = [...data.my_choices];
        render();
      } catch (error) {
        showError(error.message);
      } finally {
        refreshPromise = null;
        if (refreshQueued) {
          refreshQueued = false;
          refresh();
        }
      }
    })();

    return refreshPromise;
  }

  function render() {
    if (!state) return;
    const { room, players, me, is_host: isHost, result } = state;
    const ready = players.filter((p) => p.ready).length;
    $('round-number').textContent = room.round_no;
    $('room-status').textContent = room.status === 'revealed' ? '結果公開' : '投票中';
    $('ready-count').textContent = ready;
    $('player-count').textContent = players.length;
    $('progress-bar').style.width = `${players.length ? (ready / players.length) * 100 : 0}%`;

    const teamA = players.filter((p) => p.team === 'A');
    const teamB = players.filter((p) => p.team === 'B');
    renderTeam('A', teamA, isHost);
    renderTeam('B', teamB, isHost);

    $('join-card').hidden = Boolean(me) || room.status === 'revealed';
    $('host-panel').hidden = !isHost;
    $('auto-reveal').checked = room.auto_reveal;
    $('lobby-ban').checked = room.lobby_ban;
    $('reveal-button').hidden = room.status === 'revealed';
    $('reset-button').hidden = room.status !== 'revealed';

    $('voting-panel').hidden = !me || room.status === 'revealed';
    $('spectator-note').hidden = !(isHost && !me && room.status === 'voting');
    $('results-panel').hidden = room.status !== 'revealed';

    if (me && room.status === 'voting') {
      $('my-team').textContent = `TEAM ${me.team}`;
      renderChoices();
      renderHeroes();
      const locked = Boolean(me.ready);
      $('submit-vote').hidden = locked;
      $('pass-vote').hidden = locked;
      $('edit-vote').hidden = !locked;
      document.querySelectorAll('.hero-button, .choice-slot').forEach((el) => { el.disabled = locked; });
      $('vote-message').textContent = locked
        ? (state.my_choices.length ? '投票済みです。結果公開まで他の人の票は見えません。' : '今回はパスで確定しています。')
        : '3体選ぶか、パスを押してください。';
    }

    if (result && room.status === 'revealed') renderResults(result);
  }

  function renderTeam(team, players, isHost) {
    $(`team-${team.toLowerCase()}-count`).textContent = `${players.length} / 5`;
    const container = $(`team-${team.toLowerCase()}-list`);
    container.innerHTML = '';
    players.forEach((player) => {
      const row = document.createElement('div');
      row.className = `player-row ${player.ready ? 'ready' : ''}`;
      row.innerHTML = `
        <div class="player-name"><strong>${escapeHtml(player.name)}</strong></div>
        <div>
          <span class="ready-chip">${player.ready ? '投票済み' : '未投票'}</span>
          ${isHost ? `<button class="kick-button" data-player-id="${player.id}" type="button">退出</button>` : ''}
        </div>`;
      container.appendChild(row);
    });
    for (let i = players.length; i < 5; i += 1) {
      const empty = document.createElement('div');
      empty.className = 'player-row empty';
      empty.textContent = '空きスロット';
      container.appendChild(empty);
    }
    container.querySelectorAll('.kick-button').forEach((button) => {
      button.addEventListener('click', () => kickPlayer(button.dataset.playerId));
    });
  }

  function renderChoices() {
    document.querySelectorAll('.choice-slot').forEach((slot, index) => {
      const hero = selected[index];
      slot.classList.toggle('filled', Boolean(hero));
      slot.querySelector('.selected-hero').textContent = hero || '未選択';
    });
  }

  function allHeroEntries() {
    return Object.entries(state.heroes).flatMap(([role, heroes]) => heroes.map((hero) => ({ hero, role })));
  }

  function renderHeroes() {
    const grid = $('hero-grid');
    grid.innerHTML = '';
    const query = searchText.toLocaleLowerCase();
    allHeroEntries()
      .filter(({ hero, role }) => (activeRole === 'All' || role === activeRole) && hero.toLocaleLowerCase().includes(query))
      .forEach(({ hero, role }) => {
        const button = document.createElement('button');
        const rank = selected.indexOf(hero);
        button.type = 'button';
        button.className = `hero-button ${rank >= 0 ? 'selected' : ''}`;
        button.dataset.rankLabel = rank >= 0 ? `${[7, 5, 3][rank]} POINTS` : '';
        button.innerHTML = `<strong>${escapeHtml(hero)}</strong><span>${role}</span>`;
        button.addEventListener('click', () => toggleHero(hero));
        grid.appendChild(button);
      });
  }

  function toggleHero(hero) {
    const index = selected.indexOf(hero);
    if (index >= 0) selected.splice(index, 1);
    else if (selected.length < 3) selected.push(hero);
    else $('vote-message').textContent = 'すでに3体選択しています。先に候補を外してください。';
    renderChoices();
    renderHeroes();
  }

  function renderResults(result) {
    $('first-team-note').textContent = result.first_team
      ? `最初にBANを確定したチーム：TEAM ${result.first_team}`
      : '有効な投票がありませんでした。';
    const cards = $('ban-cards');
    cards.innerHTML = '';
    result.bans.forEach((ban, index) => {
      const card = document.createElement('article');
      card.className = `ban-card ${ban.kind === 'lobby' ? 'lobby' : ''}`;
      card.dataset.index = String(index + 1);
      const source = ban.kind === 'lobby' ? 'LOBBY BAN' : `TEAM ${ban.source_team} BAN`;
      card.innerHTML = `
        <span class="ban-kind">${source}</span>
        <h3>${escapeHtml(ban.hero)}</h3>
        <p>${ban.role} · ${ban.score}点</p>`;
      cards.appendChild(card);
    });
    if (!result.bans.length) cards.innerHTML = '<p>有効なBAN候補がありませんでした。</p>';
    renderScores('A', result.scores.A || {});
    renderScores('B', result.scores.B || {});
  }

  function renderScores(team, scores) {
    const container = $(`score-${team.toLowerCase()}`);
    const rows = Object.entries(scores).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 12);
    container.innerHTML = rows.length ? '' : '<p>投票なし</p>';
    rows.forEach(([hero, score]) => {
      const row = document.createElement('div');
      row.className = 'score-row';
      row.innerHTML = `<span>${escapeHtml(hero)}</span><strong>${score}</strong>`;
      container.appendChild(row);
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    }[char]));
  }

  async function kickPlayer(playerId) {
    if (!confirm('この参加者をルームから退出させますか？')) return;
    try {
      await api(`/api/rooms/${code}/kick`, { method: 'POST', body: JSON.stringify({ player_id: playerId }) });
      await refresh();
    } catch (error) { showError(error.message); }
  }

  $('join-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = $('player-name').value.trim();
    const team = document.querySelector('input[name="team"]:checked')?.value;
    try {
      const data = await api(`/api/rooms/${code}/join`, {
        method: 'POST',
        body: JSON.stringify({ name, team }),
      });
      localStorage.setItem(playerKey, data.player_token);
      selected = [];
      await refresh();
    } catch (error) { showError(error.message); }
  });

  $('submit-vote').addEventListener('click', async () => {
    if (selected.length !== 3) {
      $('vote-message').textContent = '第1〜第3候補まで3体選んでください。';
      return;
    }
    try {
      await api(`/api/rooms/${code}/vote`, { method: 'POST', body: JSON.stringify({ choices: selected }) });
      await refresh();
    } catch (error) { $('vote-message').textContent = error.message; }
  });

  $('pass-vote').addEventListener('click', async () => {
    if (!confirm('ヒーローを選ばず、今回はパスしますか？')) return;
    try {
      selected = [];
      await api(`/api/rooms/${code}/vote`, { method: 'POST', body: JSON.stringify({ choices: [] }) });
      await refresh();
    } catch (error) { $('vote-message').textContent = error.message; }
  });

  $('edit-vote').addEventListener('click', async () => {
    try {
      await api(`/api/rooms/${code}/unready`, { method: 'POST', body: '{}' });
      await refresh();
    } catch (error) { showError(error.message); }
  });

  $('leave-button').addEventListener('click', async () => {
    if (!confirm('このルームから退出しますか？')) return;
    try {
      await api(`/api/rooms/${code}/leave`, { method: 'POST', body: '{}' });
    } catch (_) { /* local cleanup still applies */ }
    localStorage.removeItem(playerKey);
    location.href = '/';
  });

  $('reveal-button').addEventListener('click', async () => {
    try {
      await api(`/api/rooms/${code}/reveal`, { method: 'POST', body: '{}' });
      await refresh();
    } catch (error) { showError(error.message); }
  });

  $('reset-button').addEventListener('click', async () => {
    if (!confirm('投票をリセットして次のラウンドへ進みますか？')) return;
    try {
      await api(`/api/rooms/${code}/reset`, { method: 'POST', body: '{}' });
      selected = [];
      await refresh();
    } catch (error) { showError(error.message); }
  });

  function queueSettingsSave() {
    clearTimeout(settingsTimer);
    settingsTimer = setTimeout(async () => {
      try {
        await api(`/api/rooms/${code}/settings`, {
          method: 'POST',
          body: JSON.stringify({
            auto_reveal: $('auto-reveal').checked,
            lobby_ban: $('lobby-ban').checked,
          }),
        });
      } catch (error) { showError(error.message); }
    }, 250);
  }
  $('auto-reveal').addEventListener('change', queueSettingsSave);
  $('lobby-ban').addEventListener('change', queueSettingsSave);

  $('hero-search').addEventListener('input', (event) => {
    searchText = event.target.value;
    renderHeroes();
  });
  $('role-filters').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-role]');
    if (!button) return;
    activeRole = button.dataset.role;
    document.querySelectorAll('#role-filters button').forEach((item) => item.classList.toggle('active', item === button));
    renderHeroes();
  });
  document.querySelectorAll('.choice-slot').forEach((slot) => {
    slot.addEventListener('click', () => {
      const index = Number(slot.dataset.slot);
      if (selected[index]) {
        selected.splice(index, 1);
        renderChoices();
        renderHeroes();
      }
    });
  });

  $('copy-link').addEventListener('click', async () => {
    await navigator.clipboard.writeText(location.href);
    $('copy-link').textContent = 'コピーしました';
    setTimeout(() => { $('copy-link').textContent = '招待URLをコピー'; }, 1500);
  });

  $('copy-result').addEventListener('click', async () => {
    if (!state?.result) return;
    const lines = state.result.bans.map((ban, index) => {
      const source = ban.kind === 'lobby' ? 'LOBBY' : `TEAM ${ban.source_team}`;
      return `${index + 1}. ${ban.hero} (${source})`;
    });
    await navigator.clipboard.writeText(`ROOM ${code} BAN\n${lines.join('\n')}`);
    $('copy-result').textContent = 'コピーしました';
    setTimeout(() => { $('copy-result').textContent = 'BAN結果をコピー'; }, 1500);
  });

  if (typeof io === 'function') {
    const socket = io({
      transports: ['websocket', 'polling'],
      upgrade: true,
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 500,
      reconnectionDelayMax: 3000,
      timeout: 10000,
    });

    socket.on('connect', () => {
      $('connection-message').textContent = 'リアルタイム接続中';
      $('connection-message').classList.add('connected');
      $('connection-message').hidden = false;
      setTimeout(() => {
        if (socket.connected) $('connection-message').hidden = true;
      }, 1200);
      socket.emit('join_room', { room_code: code });
      refresh();
    });

    socket.on('connect_error', () => {
      $('connection-message').classList.remove('connected');
      $('connection-message').textContent = 'リアルタイム接続を再試行中です。画面は自動更新されます。';
      $('connection-message').hidden = false;
    });

    socket.on('disconnect', () => {
      $('connection-message').classList.remove('connected');
      $('connection-message').textContent = 'リアルタイム接続を再試行中です。画面は自動更新されます。';
      $('connection-message').hidden = false;
    });

    socket.on('room_updated', (payload) => {
      if (payload.room_code !== code) return;
      lastRealtimeEvent = Date.now();
      refresh();
    });
  }

  // Render側でWebSocketが一時的に切れても、最大1秒ほどで全端末へ反映する保険。
  setInterval(() => {
    if (document.visibilityState === 'visible') refresh();
  }, 1000);
  window.addEventListener('focus', refresh);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh();
  });

  refresh();
})();
