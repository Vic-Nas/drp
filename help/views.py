from functools import cache
from pathlib import Path

from django.shortcuts import render
from django.views.decorators.cache import cache_page


def index(request):
    return render(request, 'help/index.html', {
        'readme_html': _get_readme_html(),
    })


# @cache_page(60 * 60 * 24)
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
    html = html.replace('href="LICENSE"', 'href="https://github.com/vicnasdev/drp/blob/main/LICENSE"')
    return html


@cache
def _get_parser_info():
    from cli.drp import build_parser, COMMANDS

    parser = build_parser()

    # Find the subparser action that has _name_parser_map (argparse internals).
    # Not all _group_actions have choices — iterating group.choices on the wrong
    # group silently produces nothing, which is why commands appeared empty.
    sub_map = {}
    for action in parser._subparsers._group_actions:
        if hasattr(action, '_name_parser_map'):
            sub_map = action._name_parser_map
            break

    # COMMANDS is the single source of truth for order + help strings.
    # sub.description is always empty — subparsers are added with help=, not description=.
    commands = []
    for name, _, help_str in COMMANDS:
        sub = sub_map.get(name)
        commands.append({
            'name': name,
            'help': help_str,
            'epilog': (sub.epilog or '').strip() if sub else '',
        })

    return {
        'description': parser.description,
        'epilog': (parser.epilog or '').strip(),
        'commands': commands,
    }