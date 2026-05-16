document.querySelectorAll("[data-nav-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const nav = button.closest("[data-nav]");
    const isOpen = nav.classList.toggle("nav-open");
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });
});
