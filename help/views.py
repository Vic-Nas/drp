from django.shortcuts import render


def index(request):
    return render(request, 'help/index.html')


def cli(request):
    return render(request, 'help/cli.html')


def expiry(request):
    return render(request, 'help/expiry.html')


def plans(request):
    return render(request, 'help/plans.html')


def privacy(request):
    return render(request, 'help/privacy.html')