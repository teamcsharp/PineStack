/* Slide out the desktop's one real Tech rail over any view. Moving or
   copying controls would detach their listeners and split their state. */
(function () {
  'use strict';

  var tab = document.getElementById('techDrawerTab');
  var rail = document.getElementById('techRail');
  var backdrop = document.getElementById('techDrawerBackdrop');
  if (!tab || !rail || !backdrop) return;

  function opened() { return document.body.classList.contains('tech-drawer-open'); }

  function show(want) {
    document.body.classList.toggle('tech-drawer-open', !!want);
    backdrop.hidden = !want;
    tab.setAttribute('aria-expanded', want ? 'true' : 'false');
    tab.setAttribute('aria-label', want ? 'Close Tech controls' : 'Open Tech controls');
    tab.title = want ? 'Close Pine Box Tech controls' : 'Slide out Pine Box Tech controls';
  }

  tab.addEventListener('click', function () { show(!opened()); });
  backdrop.addEventListener('click', function () { show(false); });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' || !opened()) return;
    show(false);
    tab.focus();
    event.stopPropagation();
  }, true);

  /* Choosing another view should expose it immediately. Settings that
     stay in the rail (routing, levels, tablet controls) leave it open. */
  rail.addEventListener('click', function (event) {
    var target = event.target.closest('[data-view], #stationBtn');
    if (target && opened()) show(false);
  });
})();
