const hiddenElements = document.querySelectorAll(".hidden");

const observer = new IntersectionObserver((entries) => {

    entries.forEach((entry) => {

        if (entry.isIntersecting) {

            entry.target.classList.add("show");

        }

    });

}, {
    threshold: 0.2
});

hiddenElements.forEach((element) => {

    observer.observe(element);

});
// ===========================
// Mobile Navigation
// ===========================

const menuButton = document.querySelector(".menu-toggle");
const nav = document.querySelector("nav");
const navLinks = document.querySelectorAll("nav a");

// Open / Close Menu
menuButton.addEventListener("click", () => {

    nav.classList.toggle("active");

});

// Close menu after clicking a navigation link
navLinks.forEach((link) => {

    link.addEventListener("click", () => {

        nav.classList.remove("active");

    });

});

// ===========================
// Smooth Scroll — Browse Articles Button (signet.html only)
// ===========================

const browseButton = document.querySelector('.btn-primary[href="#featured"]');

if (browseButton && document.querySelector("#featured")) {
    browseButton.addEventListener("click", function (e) {
        e.preventDefault();

        document.querySelector("#featured").scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    });
}