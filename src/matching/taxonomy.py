"""Tech-skill taxonomy: canonical skill name -> synonym phrases.

The scorer scans a job's title + description for these phrases (case-insensitive,
word-boundary aware) to detect the job's tech stack. Add or tune entries freely;
canonical names on the left are what you reference in preference.json "skills".
"""
from __future__ import annotations

import re

TAXONOMY: dict[str, list[str]] = {
    # PHP world
    "php": ["php", "php7", "php8", "php 7", "php 8"],
    "laravel": ["laravel", "lumen", "livewire", "eloquent", "inertia", "inertia.js", "filament"],
    "symfony": ["symfony"],
    "zend": ["zend", "laminas"],
    "codeigniter": ["codeigniter"],
    "wordpress": ["wordpress", "woocommerce"],
    "drupal": ["drupal"],
    "magento": ["magento", "adobe commerce"],
    "shopware": ["shopware"],
    "typo3": ["typo3"],
    # Frontend
    "vue": ["vue", "vuejs", "vue.js", "vue3", "nuxt", "nuxt.js", "vuex", "pinia", "quasar"],
    "react": ["react", "reactjs", "react.js", "next.js", "nextjs", "redux"],
    "angular": ["angular", "angularjs", "ngrx", "rxjs"],
    "svelte": ["svelte", "sveltekit"],
    # NB: no bare "js" - it would also fire on "Vue.js" / "Node.js" / "Next.js".
    "javascript": ["javascript", "vanilla js", "es6", "ecmascript"],
    "typescript": ["typescript"],
    "jquery": ["jquery"],
    "html": ["html", "html5"],
    "css": ["css", "css3", "scss", "sass"],
    "tailwind": ["tailwind", "tailwindcss", "tailwind css"],
    "bootstrap": ["bootstrap"],
    # Backend JS
    "nodejs": ["node", "node.js", "nodejs", "express", "express.js", "nestjs", "nest.js", "deno", "bun"],
    # Databases
    "mysql": ["mysql", "mariadb"],
    "postgresql": ["postgresql", "postgres"],
    "sql": ["sql", "sql server", "mssql", "sqlite", "oracle db"],
    "mongodb": ["mongodb", "mongo", "nosql"],
    "redis": ["redis", "memcached"],
    "elasticsearch": ["elasticsearch", "opensearch", "elastic search"],
    # APIs & messaging
    "rest": ["restful", "rest api", "rest apis", "restapi", "web services", "api design",
             "api development", "api integration", "json api"],
    "graphql": ["graphql"],
    "rabbitmq": ["rabbitmq"],
    "kafka": ["kafka"],
    # DevOps & cloud
    "docker": ["docker", "docker compose", "containerisation", "containerization"],
    "kubernetes": ["kubernetes", "k8s", "helm", "openshift"],
    "aws": ["aws", "amazon web services", "ec2", "lambda", "cloudformation"],
    "azure": ["azure"],
    "gcp": ["gcp", "google cloud"],
    "cicd": ["ci/cd", "cicd", "continuous integration", "continuous delivery", "jenkins",
             "gitlab ci", "github actions", "bitbucket pipelines"],
    "git": ["git", "github", "gitlab", "bitbucket", "version control"],
    "linux": ["linux", "ubuntu", "debian", "bash", "shell scripting"],
    "terraform": ["terraform", "ansible", "infrastructure as code"],
    # Python world
    "python": ["python"],
    "django": ["django"],
    "flask": ["flask"],
    "fastapi": ["fastapi"],
    # Other languages / stacks
    "java": ["java", "jvm", "maven", "gradle", "hibernate"],
    "spring": ["spring boot", "springboot", "spring framework", "spring mvc"],
    "csharp": ["c#", "csharp", ".net", "dotnet", "asp.net", ".net core"],
    "cpp": ["c++"],
    "golang": ["golang"],
    "ruby": ["ruby", "ruby on rails", "rails"],
    "kotlin": ["kotlin"],
    "scala": ["scala"],
    "rust": ["rust"],
    "mobile": ["react native", "flutter", "ios development", "android development", "swiftui"],
    # Quality
    "testing": ["phpunit", "pest", "jest", "cypress", "playwright", "selenium", "vitest",
                "unit testing", "unit tests", "tdd", "test-driven"],
}


def _phrase_to_regex(phrase: str) -> str:
    # Escape, allow flexible whitespace/hyphens between words, and require
    # non-word characters around the phrase (handles "c#", ".net", "vue.js").
    parts = [re.escape(p) for p in phrase.split()]
    body = r"[\s\-]+".join(parts)
    return rf"(?<![\w#+]){body}(?![\w#+])"


_COMPILED: dict[str, re.Pattern] = {
    skill: re.compile("|".join(_phrase_to_regex(p) for p in phrases), re.IGNORECASE)
    for skill, phrases in TAXONOMY.items()
}


def detect_skills(text: str) -> list[str]:
    """Return canonical skills detected in free text, in taxonomy order."""
    return [skill for skill, pattern in _COMPILED.items() if pattern.search(text)]
