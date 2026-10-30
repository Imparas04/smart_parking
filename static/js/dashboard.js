(function () {
  var el = document.getElementById('chart-data');
  if (!el) return;
  if (typeof Chart === 'undefined') {
    document.querySelectorAll('.chart-box').forEach(function (b) { b.innerHTML = '<p class="muted">Charts could not be loaded.</p>'; });
    return;
  }
  var d = JSON.parse(el.textContent);
  var GREEN = '#22c55e', RED = '#ef4444', GREY = '#94a3b8', BLUE = '#4f46e5', AMBER = '#f59e0b', PURPLE = '#8b5cf6';
  Chart.defaults.font.family = 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
  function make(id, cfg) {
    var c = document.getElementById(id);
    if (!c) return;
    cfg.options = Object.assign({responsive: true, maintainAspectRatio: false}, cfg.options || {});
    new Chart(c, cfg);
  }
  make('chartSlots', {type: 'doughnut', data: {labels: d.slot_status.labels,
    datasets: [{data: d.slot_status.values, backgroundColor: [GREEN, RED, GREY]}]},
    options: {plugins: {legend: {position: 'bottom'}}}});
  make('chartStatus', {type: 'doughnut', data: {labels: d.booking_status.labels,
    datasets: [{data: d.booking_status.values, backgroundColor: [BLUE, AMBER, GREEN, GREY, PURPLE]}]},
    options: {plugins: {legend: {position: 'bottom'}}}});
  make('chartBookings', {type: 'bar', data: {labels: d.daily.labels,
    datasets: [{label: 'Bookings', data: d.daily.bookings, backgroundColor: BLUE}]},
    options: {plugins: {legend: {display: false}}, scales: {y: {beginAtZero: true, ticks: {precision: 0}}}}});
  make('chartRevenue', {type: 'line', data: {labels: d.daily.labels,
    datasets: [{label: 'Revenue (INR)', data: d.daily.revenue, borderColor: GREEN, backgroundColor: 'rgba(34,197,94,.15)', fill: true, tension: .25}]},
    options: {plugins: {legend: {display: false}}, scales: {y: {beginAtZero: true}}}});
  make('chartLocations', {type: 'bar', data: {labels: d.locations.labels, datasets: [
    {label: 'Available', data: d.locations.available, backgroundColor: GREEN},
    {label: 'Occupied', data: d.locations.occupied, backgroundColor: RED},
    {label: 'Unavailable', data: d.locations.unavailable, backgroundColor: GREY}]},
    options: {indexAxis: 'y', plugins: {legend: {position: 'bottom'}},
      scales: {x: {stacked: true, beginAtZero: true, ticks: {precision: 0}}, y: {stacked: true}}}});
})();
