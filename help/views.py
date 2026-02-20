from functools import cache

from django.shortcuts import render
from django.views.decorators.cache import cache_page


def index(request):
    return render(request, 'help/index.html')


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
def _get_parser_info():
    from cli.drp import build_parser
    parser = build_parser()

    commands = []
    for group in parser._subparsers._group_actions:
        for name, sub in group.choices.items():
            commands.append({
                'name': name,
                'help': sub.description or '',
                'epilog': sub.epilog or '',
            })

    return {
        'description': parser.description,
        'epilog': parser.epilog or '',
        'commands': commands,
    }