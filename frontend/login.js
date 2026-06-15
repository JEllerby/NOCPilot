document
  .getElementById("loginForm")
  .addEventListener("submit", function(event) {
    event.preventDefault();

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    if (username === "admin" && password === "nocpilot123") {
      localStorage.setItem("isLoggedIn", "true");
      window.location.href = "index.html";
    } else {
      document.getElementById("error").textContent =
        "Invalid username or password";
    }
});