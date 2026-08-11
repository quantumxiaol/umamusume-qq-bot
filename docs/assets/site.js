const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");

if (navToggle && siteNav) {
  navToggle.addEventListener("click", () => {
    const open = siteNav.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(open));
  });

  siteNav.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      siteNav.classList.remove("open");
      navToggle.setAttribute("aria-expanded", "false");
    }
  });
}

const roleSearch = document.querySelector("#role-search");
const roleItems = [...document.querySelectorAll("#role-grid span")];
const roleEmpty = document.querySelector("#role-empty");

if (roleSearch && roleEmpty) {
  roleSearch.addEventListener("input", () => {
    const query = roleSearch.value.trim().toLocaleLowerCase("zh-CN");
    let visibleCount = 0;
    roleItems.forEach((item) => {
      const matches = item.textContent.toLocaleLowerCase("zh-CN").includes(query);
      item.hidden = !matches;
      visibleCount += Number(matches);
    });
    roleEmpty.hidden = visibleCount !== 0;
  });
}

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;

    const originalLabel = button.textContent;
    try {
      await navigator.clipboard.writeText(target.innerText);
      button.textContent = "已复制";
    } catch {
      button.textContent = "请手动复制";
    }
    window.setTimeout(() => {
      button.textContent = originalLabel;
    }, 1600);
  });
});

const navLinks = [...document.querySelectorAll(".site-nav a")];
const sections = navLinks
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      navLinks.forEach((link) => {
        link.classList.toggle("active", link.getAttribute("href") === `#${visible.target.id}`);
      });
    },
    { rootMargin: "-25% 0px -65%", threshold: [0, 0.25, 0.7] },
  );
  sections.forEach((section) => observer.observe(section));
}
