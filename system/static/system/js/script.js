document.getElementById("toggle-btn").addEventListener("click", function () {
    let sidebar = document.getElementById("sidebar");
    let toggleIcon = document.getElementById("toggle-icon");
    let companyName = document.getElementById("company-name");
    let smallName = document.getElementById("name-small");
    sidebar.classList.toggle("collapsed");
    toggleIcon.classList.toggle("rotated");
    companyName.style.display = sidebar.classList.contains("collapsed") ? "none" : "block";
    smallName.style.display = sidebar.classList.contains("collapsed") ? "block" : "none";
});

function toggleDarkMode() {
    document.documentElement.classList.toggle("dark-mode"); // Apply to the root element
    const isDarkMode = document.documentElement.classList.contains("dark-mode");
    localStorage.setItem("theme", isDarkMode ? "dark" : "light");
}

// Apply dark mode on page load if it was previously enabled
(function () {
    if (localStorage.getItem("theme") === "dark") {
        document.documentElement.classList.add("dark-mode");
    }
})();
