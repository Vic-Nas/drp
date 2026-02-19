# drp CLI reference

## Overview

```
usage: drp [-h] [--version] {setup,login,up,get,rm,mv,renew,ls,status} ...

Drop text and files from the command line.

positional arguments:
  {setup,login,up,get,rm,mv,renew,ls,status}
    setup               Configure host & login
    login               Log in to drp
    up                  Upload a file or text
    get                 Download a drop
    rm                  Delete a drop
    mv                  Rename a drop key
    renew               Renew a drop expiry
    ls                  List your drops (requires login)
    status              Show config

options:
  -h, --help            show this help message and exit
  --version, -V         show program's version number and exit
```

## drp setup

```
usage: drp setup [-h]

options:
  -h, --help  show this help message and exit
```

## drp login

```
usage: drp login [-h]

options:
  -h, --help  show this help message and exit
```

## drp up

```
usage: drp up [-h] [--key KEY] target

positional arguments:
  target             File path or text string to upload

options:
  -h, --help         show this help message and exit
  --key KEY, -k KEY  Custom key (default: auto from filename)
```

## drp get

```
usage: drp get [-h] [--output OUTPUT] key

positional arguments:
  key                   Drop key to download

options:
  -h, --help            show this help message and exit
  --output OUTPUT, -o OUTPUT
                        Output filename (files only)
```

## drp rm

```
usage: drp rm [-h] key

positional arguments:
  key         Drop key to delete

options:
  -h, --help  show this help message and exit
```

## drp mv

```
usage: drp mv [-h] key new_key

positional arguments:
  key         Current drop key
  new_key     New key

options:
  -h, --help  show this help message and exit
```

## drp renew

```
usage: drp renew [-h] key

positional arguments:
  key         Drop key to renew

options:
  -h, --help  show this help message and exit
```

## drp ls

```
usage: drp ls [-h]

options:
  -h, --help  show this help message and exit
```

## drp status

```
usage: drp status [-h]

options:
  -h, --help  show this help message and exit
```
