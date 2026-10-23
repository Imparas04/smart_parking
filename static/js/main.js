/* Site-wide behaviour. No inline scripts are used anywhere (Content-Security-Policy: script-src 'self'). */
document.addEventListener('DOMContentLoaded', function () {
  var toggle = document.getElementById('navToggle');
  var links = document.getElementById('navLinks');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      var open = links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // <select data-autosubmit> submits its form when changed
  document.querySelectorAll('select[data-autosubmit]').forEach(function (sel) {
    sel.addEventListener('change', function () { if (sel.form) sel.form.submit(); });
  });

  // dismissible messages
  document.querySelectorAll('.alert .alert-close').forEach(function (btn) {
    btn.addEventListener('click', function () { var a = btn.closest('.alert'); if (a) a.remove(); });
  });

  // connect field errors to their inputs for screen readers
  document.querySelectorAll('.field.has-error').forEach(function (field) {
    var input = field.querySelector('input, select, textarea');
    var errors = field.querySelector('.errors');
    if (input) {
      input.setAttribute('aria-invalid', 'true');
      if (errors) input.setAttribute('aria-describedby', errors.id);
    }
  });
  var firstError = document.querySelector('.field.has-error input, .field.has-error select, .field.has-error textarea');
  if (firstError) firstError.focus();
});

function resetLoading() {
  document.querySelectorAll('.is-loading').forEach(function (b) {
    b.disabled = false;
    b.classList.remove('is-loading');
    if (b.dataset.label) { b.textContent = b.dataset.label; delete b.dataset.label; }
  });
}

// One delegated submit handler: optional confirmation (data-confirm) and double-submit protection.
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (!(form instanceof HTMLFormElement)) return;
  var message = form.getAttribute('data-confirm') || (e.submitter && e.submitter.getAttribute('data-confirm'));
  if (message && !window.confirm(message)) { e.preventDefault(); return; }
  if (e.defaultPrevented || form.method.toLowerCase() !== 'post') return;
  setTimeout(function () {
    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (b) {
      b.disabled = true;
      b.classList.add('is-loading');
      if (b.tagName === 'BUTTON') { b.dataset.label = b.textContent; b.textContent = 'Please wait\u2026'; }
    });
  }, 0);
});

// Coming back with the browser Back button must not leave buttons stuck in the loading state.
window.addEventListener('pageshow', function (e) { if (e.persisted) resetLoading(); });
