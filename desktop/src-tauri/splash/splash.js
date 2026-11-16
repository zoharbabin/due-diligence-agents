// Called by the shell when the local service cannot start.
window.showError = function (text) {
  document.getElementById('spin').style.display = 'none'
  document.getElementById('msg').textContent = 'The app could not start.'
  document.getElementById('err').textContent = text
}
