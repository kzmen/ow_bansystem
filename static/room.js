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
  let selectionDirty = false;
  let lastRoundNo = null;

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
    try {
      const data = await api(`/api/rooms/${code}/state`);
      const roundChanged = lastRoundNo !== null && lastRoundNo !== data.room.round_no;
      state = data;
      clearError();

      // リアルタイム更新で、投票確定前に選んでいる候補を消さない。
      // 初回表示・ラウンド変更・投票確定時だけサーバーの内容へ同期する。
      if (!data.me) {
        selected = [];
        selectionDirty = false;
      } else if (roundChanged || data.me.ready || !selectionDirty) {
        selected = [...data.my_choices];
        selectionDirty = false;
      }
      lastRoundNo = data.room.round_no;
      render();
    } catch (error) {
      showError(error.message);
    }
  }

  function render() {
    if (!state) return;
    const { room, players, me, is_host: isHost, result } = state;
    const eligiblePlayers = players.filter((p) => ['A', 'B'].includes(p.team));
    const ready = eligiblePlayers.filter((p) => p.ready).length;
    $('round-number').textContent = room.round_no;
    $('room-status').textContent = room.status === 'revealed' ? '結果公開' : '投票中';
    $('ready-count').textContent = ready;
    $('player-count').textContent = eligiblePlayers.length;
    $('progress-bar').style.width = `${eligiblePlayers.length ? (ready / eligiblePlayers.length) * 100 : 0}%`;

    const teamU = players.filter((p) => p.team === 'U');
    const teamA = players.filter((p) => p.team === 'A');
    const teamB = players.filter((p) => p.team === 'B');
    renderTeam('U', teamU, isHost);
    renderTeam('A', teamA, isHost);
    renderTeam('B', teamB, isHost);

    $('join-card').hidden = Boolean(me) || room.status === 'revealed';
    $('host-panel').hidden = !isHost;
    $('auto-reveal').checked = room.auto_reveal;
    $('lobby-ban').checked = room.lobby_ban;
    $('reveal-button').hidden = room.status === 'revealed';
    $('reset-button').hidden = room.status !== 'revealed';

    const canVote = Boolean(me && ['A', 'B'].includes(me.team));
    $('voting-panel').hidden = !canVote || room.status === 'revealed';
    $('unassigned-note').hidden = !(me && me.team === 'U' && room.status === 'voting');
    $('spectator-note').hidden = !(isHost && !me && room.status === 'voting');
    $('results-panel').hidden = room.status !== 'revealed';

    if (canVote && room.status === 'voting') {
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
    const count = $(`team-${team.toLowerCase()}-count`);
    count.textContent = team === 'U' ? String(players.length) : `${players.length} / 5`;
    const container = $(`team-${team.toLowerCase()}-list`);
    container.innerHTML = '';
    players.forEach((player) => {
      const row = document.createElement('div');
      row.className = `player-row ${player.ready ? 'ready' : ''}`;
      const status = player.team === 'U' ? '待機中' : (player.ready ? '投票済み' : '未投票');
      const hostControls = isHost ? `
        <div class="player-controls">
          <button class="move-button ${player.team === 'U' ? 'active' : ''}" data-player-id="${player.id}" data-team="U" type="button">未所属</button>
          <button class="move-button ${player.team === 'A' ? 'active' : ''}" data-player-id="${player.id}" data-team="A" type="button">A</button>
          <button class="move-button ${player.team === 'B' ? 'active' : ''}" data-player-id="${player.id}" data-team="B" type="button">B</button>
          <button class="kick-button" data-player-id="${player.id}" type="button">退出</button>
        </div>` : `<span class="ready-chip">${status}</span>`;
      row.innerHTML = `
        <div class="player-name"><strong>${escapeHtml(player.name)}</strong></div>
        ${hostControls}`;
      container.appendChild(row);
    });
    if (team !== 'U') {
      for (let i = players.length; i < 5; i += 1) {
        const empty = document.createElement('div');
        empty.className = 'player-row empty';
        empty.textContent = '空きスロット';
        container.appendChild(empty);
      }
    } else if (!players.length) {
      const empty = document.createElement('div');
      empty.className = 'player-row empty';
      empty.textContent = '待機中の参加者はいません';
      container.appendChild(empty);
    }
    container.querySelectorAll('.move-button').forEach((button) => {
      button.addEventListener('click', () => movePlayer(button.dataset.playerId, button.dataset.team));
    });
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
    selectionDirty = true;
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

  async function movePlayer(playerId, team) {
    try {
      await api(`/api/rooms/${code}/move`, {
        method: 'POST',
        body: JSON.stringify({ player_id: playerId, team }),
      });
      await refresh();
    } catch (error) { showError(error.message); }
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
    const team = document.querySelector('input[name="team"]:checked')?.value || 'U';
    try {
      const data = await api(`/api/rooms/${code}/join`, {
        method: 'POST',
        body: JSON.stringify({ name, team }),
      });
      localStorage.setItem(playerKey, data.player_token);
      selected = [];
      selectionDirty = false;
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
      selectionDirty = false;
      await refresh();
    } catch (error) { $('vote-message').textContent = error.message; }
  });

  $('pass-vote').addEventListener('click', async () => {
    if (!confirm('ヒーローを選ばず、今回はパスしますか？')) return;
    try {
      selected = [];
      selectionDirty = false;
      await api(`/api/rooms/${code}/vote`, { method: 'POST', body: JSON.stringify({ choices: [] }) });
      await refresh();
    } catch (error) { $('vote-message').textContent = error.message; }
  });

  $('edit-vote').addEventListener('click', async () => {
    try {
      await api(`/api/rooms/${code}/unready`, { method: 'POST', body: '{}' });
      selectionDirty = false;
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
      selectionDirty = false;
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
        selectionDirty = true;
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
    const socket = io();
    socket.on('connect', () => {
      $('connection-message').hidden = true;
      socket.emit('join_room', { room_code: code });
    });
    socket.on('disconnect', () => {
      $('connection-message').textContent = 'リアルタイム接続が切れました。自動で再接続します。';
      $('connection-message').hidden = false;
    });
    socket.on('room_updated', (payload) => {
      if (payload.room_code === code) refresh();
    });
    setInterval(refresh, 1000);
  } else {
    // ライブラリ不要版では1秒ごとの更新で全端末へ反映します。
    setInterval(refresh, 1000);
  }

  refresh();
})();
