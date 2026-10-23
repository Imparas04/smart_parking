/* Booking form: live fee estimate from the server (the server is the source of truth for charges). */
(function () {
  var start = document.getElementById('id_start_time');
  var end = document.getElementById('id_end_time');
  var box = document.getElementById('estimate');
  if (!start || !end || !box) return;
  var url = box.dataset.url, slot = box.dataset.slot, timer, request = 0;

  // don't offer times in the past (local clock; the server re-checks everything)
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  var now = new Date();
  var min = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) + 'T' + pad(now.getHours()) + ':' + pad(now.getMinutes());
  start.min = min;
  end.min = min;

  function show(text, state) { box.hidden = false; box.textContent = text; box.dataset.state = state || ''; }

  function update() {
    if (!start.value || !end.value) { box.hidden = true; return; }
    var mine = ++request;
    show('Calculating estimated charge\u2026', 'loading');
    var q = new URLSearchParams({slot: slot, start_time: start.value, end_time: end.value});
    fetch(url + '?' + q.toString())
      .then(function (r) { return r.json().then(function (d) { return {ok: r.ok, d: d}; }); })
      .then(function (res) {
        if (mine !== request) return;  // a newer request superseded this one
        if (res.ok) {
          show('Estimated charge: \u20B9' + res.d.amount + ' (' + res.d.billing_blocks + ' hour(s) at \u20B9' + res.d.hourly_rate + '/hour)', 'ok');
        } else {
          show('Enter a valid time range to see the estimated charge.', 'error');
        }
      })
      .catch(function () { if (mine === request) show('Could not calculate the estimate right now. You can still book.', 'error'); });
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(update, 300); }
  start.addEventListener('change', schedule);
  end.addEventListener('change', schedule);
  update();
})();
