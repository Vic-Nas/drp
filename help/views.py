from functools import cache
from pathlib import Path

from django.shortcuts import render
from django.views.decorators.cache import cache_page


def index(request):
    return render(request, 'help/index.html', {
        'readme_html': _get_readme_html(),
    })


@cache_page(60 * 60 * 24)
def cli(request):
    return render(request, 'help/cli.html', {
        'parser_info': _get_parser_info(),
    })


def expiry(request):
    return render(request, 'help/expiry.html')


def plans(request):
    return render(request, 'help/plans.html')


def privacy(request):
    return render(request, 'help/privacy.html')


@cache
def _get_readme_html():
    import markdown
    readme_path = Path(__file__).resolve().parent.parent / 'README.md'
    text = readme_path.read_text()
    html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    # Fix relative LICENSE link — at /help/ it would 404
    html = html.replace('href="LICENSE"', 'href="https://github.com/vicnasdev/drp/blob/main/LICENSE"')
    return html


@cache
def _get_parser_info():
    from cli.drp import build_parser, COMMANDS
    parser = build_parser()

    # Build a lookup from the COMMANDS list — this is the source of truth for
    # help strings. sub.description is always empty because subparsers are only
    # given a `help=` kwarg, not `description=`.
    help_lookup = {name: help_str for name, _, help_str in COMMANDS}

    commands = []
    for group in parser._subparsers._group_actions:
        for name, sub in group.choices.items():
            commands.append({
                'name': name,
                'help': help_lookup.get(name, ''),
                'epilog': sub.epilog or '',
            })

    return {
        'description': parser.description,
        'epilog': parser.epilog or '',
        'commands': commands,
    }