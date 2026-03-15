/**
 * Trading Journal — Chart helpers using Chart.js
 */

const COLORS = {
    green: '#3fb950',
    red: '#f85149',
    blue: '#58a6ff',
    text: '#8b949e',
    grid: '#30363d',
    bg: '#1c2128',
    greenFill: 'rgba(63, 185, 80, 0.15)',
    redFill: 'rgba(248, 81, 73, 0.15)',
    blueFill: 'rgba(88, 166, 255, 0.08)',
};

Chart.defaults.color = COLORS.text;
Chart.defaults.borderColor = COLORS.grid;
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
Chart.defaults.font.size = 11;

/**
 * Equity curve — filled area chart (not line).
 */
function createEquityCurve(canvasId, data) {
    const labels = data.map(d => d.trade_date.slice(5)); // MM-DD
    let cumulative = 0;
    const values = data.map(d => {
        cumulative += d.total_pnl;
        return Math.round(cumulative * 100) / 100;
    });

    const ctx = document.getElementById(canvasId).getContext('2d');

    // Gradient fill
    const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
    const lastVal = values[values.length - 1] || 0;
    if (lastVal >= 0) {
        gradient.addColorStop(0, 'rgba(63, 185, 80, 0.3)');
        gradient.addColorStop(1, 'rgba(63, 185, 80, 0.02)');
    } else {
        gradient.addColorStop(0, 'rgba(248, 81, 73, 0.02)');
        gradient.addColorStop(1, 'rgba(248, 81, 73, 0.3)');
    }

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Cumulative P&L',
                data: values,
                borderColor: lastVal >= 0 ? COLORS.green : COLORS.red,
                borderWidth: 2,
                backgroundColor: gradient,
                fill: true,
                tension: 0.35,
                pointRadius: 4,
                pointBackgroundColor: lastVal >= 0 ? COLORS.green : COLORS.red,
                pointBorderColor: COLORS.bg,
                pointBorderWidth: 2,
                pointHoverRadius: 7,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#22272e',
                    borderColor: COLORS.grid,
                    borderWidth: 1,
                    titleFont: { weight: '600' },
                    callbacks: {
                        label: ctx => `$${ctx.parsed.y.toFixed(2)}`,
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxTicksLimit: 10 },
                },
                y: {
                    grid: { color: COLORS.grid },
                    ticks: {
                        callback: val => '$' + (val >= 1000 ? (val/1000).toFixed(0) + 'k' : val),
                    },
                },
            },
        },
    });
}

/**
 * Daily P&L bar chart.
 */
function createDailyBars(canvasId, data) {
    const labels = data.map(d => {
        const dt = new Date(d.trade_date + 'T12:00:00');
        return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dt.getDay()];
    });
    const values = data.map(d => d.total_pnl);
    const colors = values.map(v => v >= 0 ? COLORS.green : COLORS.red);

    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Daily P&L',
                data: values,
                backgroundColor: colors,
                borderRadius: 4,
                barPercentage: 0.6,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#22272e',
                    borderColor: COLORS.grid,
                    borderWidth: 1,
                    callbacks: {
                        label: ctx => {
                            const sign = ctx.parsed.y >= 0 ? '+' : '';
                            return `${sign}$${ctx.parsed.y.toFixed(2)}`;
                        },
                    },
                },
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    grid: { color: COLORS.grid },
                    ticks: { callback: val => '$' + val },
                },
            },
        },
    });
}

/**
 * Win/loss donut chart.
 */
function createWinLossDonut(canvasId, stats) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Wins', 'Losses', 'Breakeven'],
            datasets: [{
                data: [stats.wins, stats.losses, stats.breakeven || 0],
                backgroundColor: [COLORS.green, COLORS.red, COLORS.text],
                borderWidth: 0,
            }],
        },
        options: {
            responsive: true,
            cutout: '65%',
            plugins: {
                legend: { position: 'bottom', labels: { padding: 15 } },
            },
        },
    });
}

/**
 * Cumulative P&L line chart (simpler version for analytics).
 */
function createPnlChart(canvasId, data) {
    return createEquityCurve(canvasId, data);
}

function formatPnl(pnl) {
    const sign = pnl >= 0 ? '+' : '';
    const cls = pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : 'pnl-zero';
    return `<span class="${cls}">${sign}$${pnl.toFixed(2)}</span>`;
}
