// Dashboard client-side behavior: sparkline charts, quick meal logging, sync buttons.

(function () {
  const data = window.__DASHBOARD_DATA || {};

  // Set default meal time to now, floored to minutes.
  const mealTimeInput = document.getElementById('meal-time');
  if (mealTimeInput) {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    mealTimeInput.value = now.toISOString().slice(0, 16);
  }

  // Simple linear regression slope on last N points.
  function linearSlope(values) {
    const n = values.length;
    if (n < 2) return 0;
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    values.forEach((y, x) => {
      sumX += x;
      sumY += y;
      sumXY += x * y;
      sumXX += x * x;
    });
    const denom = n * sumXX - sumX * sumX;
    if (denom === 0) return 0;
    return (n * sumXY - sumX * sumY) / denom;
  }

  function avg(values) {
    if (!values.length) return 0;
    return values.reduce((a, b) => a + b, 0) / values.length;
  }

  // Draw a smooth area + line sparkline into containerId using points [{x, y}].
  function drawSparkline(containerId, points, options = {}) {
    const container = document.getElementById(containerId);
    if (!container || !points || points.length < 2) {
      if (container) container.innerHTML = '<div class="sparkline-empty">数据不足</div>';
      return;
    }

    const values = points.map((p) => p.y);
    const min = Math.min(...values) * (options.minPad || 0.98);
    const max = Math.max(...values) * (options.maxPad || 1.02);
    const range = max - min || 1;

    const width = 300;
    const height = 80;
    const padding = 4;

    const coords = points.map((p, i) => {
      const x = padding + (i / (points.length - 1)) * (width - padding * 2);
      const y = height - padding - ((p.y - min) / range) * (height - padding * 2);
      return { x, y, value: p.y, label: p.label };
    });

    const linePath = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
    const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${height} L ${coords[0].x} ${height} Z`;

    const last = coords[coords.length - 1];
    const dots = coords.filter((_, i) => i === 0 || i === coords.length - 1 || i % Math.ceil(coords.length / 8) === 0)
      .map((c) => `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="2.5" class="sparkline-dot"><title>${c.label}: ${c.value}${options.unit || ''}</title></circle>`)
      .join('');

    container.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
        <path d="${areaPath}" class="sparkline-area"></path>
        <path d="${linePath}" class="sparkline-path"></path>
        ${dots}
        <circle cx="${last.x.toFixed(1)}" cy="${last.y.toFixed(1)}" r="4" class="sparkline-dot"><title>${last.label}: ${last.value}${options.unit || ''}</title></circle>
      </svg>
    `;
  }

  function renderCharts() {
    const body = (data.body || []).slice(-30);
    const sleep = (data.sleep || []).slice(-30);

    // Weight chart
    const weightPoints = body.filter((p) => p.weight != null).map((p) => ({ y: p.weight, label: p.date }));
    if (weightPoints.length) {
      const latest = weightPoints[weightPoints.length - 1].y;
      const slope = linearSlope(weightPoints.map((p) => p.y));
      document.getElementById('weight-current').textContent = `${latest.toFixed(1)} kg`;
      const trendEl = document.getElementById('weight-trend');
      if (slope < -0.03) {
        trendEl.textContent = '下降中';
        trendEl.className = 'sparkline-trend down';
      } else if (slope > 0.03) {
        trendEl.textContent = '上升中';
        trendEl.className = 'sparkline-trend up';
      } else {
        trendEl.textContent = '平稳';
        trendEl.className = 'sparkline-trend neutral';
      }
      drawSparkline('weight-chart', weightPoints, { unit: ' kg' });
    }

    // Body fat chart
    const fatPoints = body.filter((p) => p.body_fat != null).map((p) => ({ y: p.body_fat, label: p.date }));
    if (fatPoints.length) {
      const latest = fatPoints[fatPoints.length - 1].y;
      const slope = linearSlope(fatPoints.map((p) => p.y));
      document.getElementById('fat-current').textContent = `${latest.toFixed(1)}%`;
      const trendEl = document.getElementById('fat-trend');
      if (slope < -0.05) {
        trendEl.textContent = '下降中';
        trendEl.className = 'sparkline-trend down';
      } else if (slope > 0.05) {
        trendEl.textContent = '上升中';
        trendEl.className = 'sparkline-trend up';
      } else {
        trendEl.textContent = '平稳';
        trendEl.className = 'sparkline-trend neutral';
      }
      drawSparkline('fat-chart', fatPoints, { unit: '%' });
    }

    // Sleep chart
    const sleepPoints = sleep.map((p) => ({ y: p.hours, label: p.date }));
    if (sleepPoints.length) {
      const latest = sleepPoints[sleepPoints.length - 1].y;
      const avgSleep = avg(sleepPoints.map((p) => p.y));
      document.getElementById('sleep-current').textContent = `${latest.toFixed(1)} h`;
      const trendEl = document.getElementById('sleep-trend');
      if (avgSleep >= 7) {
        trendEl.textContent = '充足';
        trendEl.className = 'sparkline-trend down';
      } else if (avgSleep >= 6) {
        trendEl.textContent = '略少';
        trendEl.className = 'sparkline-trend neutral';
      } else {
        trendEl.textContent = '不足';
        trendEl.className = 'sparkline-trend up';
      }
      drawSparkline('sleep-chart', sleepPoints, { unit: 'h', minPad: 0.95, maxPad: 1.05 });
    }
  }

  // Quick meal logging
  window.saveQuickMeal = async function (event) {
    event.preventDefault();
    const form = event.target;
    const submitBtn = document.getElementById('log-submit');
    const statusEl = document.getElementById('log-status');
    submitBtn.disabled = true;
    statusEl.textContent = '保存中…';

    const formData = new FormData(form);
    const payload = {
      meal_type: formData.get('meal_type'),
      eaten_at: formData.get('eaten_at') || undefined,
      description: formData.get('description'),
      estimated_kcal: formData.get('estimated_kcal') ? parseFloat(formData.get('estimated_kcal')) : null,
      protein_g: formData.get('protein_g') ? parseFloat(formData.get('protein_g')) : null,
      carb_g: formData.get('carb_g') ? parseFloat(formData.get('carb_g')) : null,
      fat_g: formData.get('fat_g') ? parseFloat(formData.get('fat_g')) : null,
      confidence: 'manual',
    };

    try {
      const response = await fetch('/api/meals/quick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `保存失败（${response.status}）`);
      statusEl.textContent = '✓ 已保存，正在刷新…';
      setTimeout(() => location.reload(), 600);
    } catch (error) {
      statusEl.textContent = `保存失败：${error.message}`;
      submitBtn.disabled = false;
    }
  };

  // Sync buttons
  async function runSync(event, defaultUrl, runningText, defaultText) {
    const button = event.currentTarget;
    const url = button.dataset.url || defaultUrl;
    const statusBox = document.getElementById('sync-status');
    button.disabled = true;
    button.textContent = runningText;
    statusBox.textContent = '正在读取最新数据…';
    try {
      const response = await fetch(url, { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `请求失败（${response.status}）`);
      statusBox.textContent = '刷新成功，正在重新生成建议…';
      location.reload();
    } catch (error) {
      statusBox.textContent = `刷新失败：${error.message}`;
      button.disabled = false;
      button.textContent = defaultText;
    }
  }

  window.syncHealth = function (event) {
    return runSync(event, '/api/sync/xiaomi', '刷新中…', '刷新健康数据');
  };
  window.syncStrava = function (event) {
    return runSync(event, '/api/sync/strava', '同步中…', '同步 Strava');
  };

  // Log tab switching
  window.switchLogTab = function (tab) {
    const textForm = document.getElementById('quick-log-form');
    const photoForm = document.getElementById('photo-log-form');
    const tabs = document.querySelectorAll('.log-tab');
    if (!textForm || !photoForm) return;

    tabs.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    if (tab === 'photo') {
      textForm.style.display = 'none';
      photoForm.style.display = 'block';
    } else {
      textForm.style.display = 'block';
      photoForm.style.display = 'none';
    }
  };

  // Photo meal logging
  const photoInput = document.querySelector('#photo-log-form input[type="file"]');
  const photoPreview = document.getElementById('photo-preview');
  if (photoInput && photoPreview) {
    photoInput.addEventListener('change', () => {
      const file = photoInput.files[0];
      if (file) {
        photoPreview.src = URL.createObjectURL(file);
        photoPreview.style.display = 'block';
      }
    });
  }

  window.savePhotoMeal = async function (event) {
    event.preventDefault();
    const form = event.target;
    const submitBtn = document.getElementById('photo-log-submit');
    const statusEl = document.getElementById('photo-log-status');
    const resultBox = document.getElementById('photo-result');
    submitBtn.disabled = true;
    statusEl.textContent = '正在识别食物，请稍候…';
    statusEl.style.color = 'var(--ink-muted)';
    if (resultBox) resultBox.style.display = 'none';

    try {
      const response = await fetch('/api/meals/analyze', {
        method: 'POST',
        body: new FormData(form),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `分析失败（${response.status}）`);

      const analysis = result.analysis || {};
      const totals = analysis.meal_total || {};
      statusEl.textContent = '✓ 已保存，正在刷新…';

      const summaryEl = document.getElementById('photo-summary');
      const totalsEl = document.getElementById('photo-totals');
      const foodsEl = document.getElementById('photo-foods');
      if (summaryEl) summaryEl.textContent = analysis.summary || '餐食分析';
      if (totalsEl) {
        totalsEl.textContent = `整餐：${totals.kcal_range || '热量未知'} · 蛋白质${totals.protein_g_range || '未知'} · 碳水${totals.carb_g_range || '未知'} · 脂肪${totals.fat_g_range || '未知'}`;
      }
      if (foodsEl) {
        foodsEl.innerHTML = '';
        (analysis.foods || []).forEach((food) => {
          const li = document.createElement('li');
          li.textContent = `${food.name || '食物'} · ${food.portion || '份量不明'}（${food.kcal_range || ''} · 蛋白质${food.protein_g_range || ''} · 碳水${food.carb_g_range || ''} · 脂肪${food.fat_g_range || ''}）`;
          foodsEl.appendChild(li);
        });
      }
      if (resultBox) resultBox.style.display = 'block';

      setTimeout(() => location.reload(), 1200);
    } catch (error) {
      statusEl.textContent = `保存失败：${error.message}`;
      statusEl.style.color = 'var(--danger)';
      submitBtn.disabled = false;
    }
  };

  // Meal logging reminders
  function checkTodayMeals() {
    const nutrition = data.nutrition || [];
    const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    const todayMeals = nutrition.filter((item) => (item.date || '').startsWith(today));
    const reminderBox = document.getElementById('meal-reminder');
    const notifyBtn = document.getElementById('enable-notifications');
    if (!reminderBox) return;

    if (todayMeals.length === 0) {
      reminderBox.style.display = 'block';
    } else {
      reminderBox.style.display = 'none';
    }

    if (notifyBtn) {
      notifyBtn.addEventListener('click', async () => {
        if (!('Notification' in window)) {
          alert('当前浏览器不支持桌面通知。');
          return;
        }
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
          notifyBtn.textContent = '提醒已开启';
          notifyBtn.disabled = true;
          scheduleMealReminders();
        } else {
          alert('需要通知权限才能提醒。');
        }
      });
    }
  }

  function scheduleMealReminders() {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const mealTimes = [
      { hour: 8, minute: 30, title: '早餐记录', body: '吃完早餐后，花 10 秒拍个照或写一句吃了什么。' },
      { hour: 12, minute: 30, title: '午餐记录', body: '吃完午餐后，花 10 秒拍个照或写一句吃了什么。' },
      { hour: 19, minute: 0, title: '晚餐记录', body: '吃完晚餐后，花 10 秒拍个照或写一句吃了什么。' },
    ];
    mealTimes.forEach((meal) => {
      const now = new Date();
      const target = new Date(now.getFullYear(), now.getMonth(), now.getDate(), meal.hour, meal.minute);
      if (target <= now) target.setDate(target.getDate() + 1);
      const delay = target - now;
      setTimeout(() => {
        new Notification(meal.title, { body: meal.body, icon: '/static/favicon.ico' });
        // Repeat daily
        setInterval(() => new Notification(meal.title, { body: meal.body, icon: '/static/favicon.ico' }), 24 * 60 * 60 * 1000);
      }, delay);
    });
  }

  renderCharts();
  checkTodayMeals();

  // Heartbeat: keeps the backend alive while this tab is open. The backend
  // shuts itself down a few minutes after the last heartbeat (tab closed).
  const beat = () => fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
  beat();
  setInterval(beat, 30 * 1000);
})();
