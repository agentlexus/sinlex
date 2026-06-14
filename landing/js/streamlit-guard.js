/** Если в DOM остался Streamlit — уйти на лендинг (кэш/залипшая вкладка). */
(function () {
  if (document.querySelector('[data-testid="stApp"]')) {
    location.replace("/?home=" + Date.now());
  }
})();
