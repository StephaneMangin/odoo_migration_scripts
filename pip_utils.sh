#!/usr/bin/env bash

local=0
versions=$(pyenv whence pip)
[ -f .python-version ] && local=1 
[[ $local == 1 ]] && versions=$(cat .python-version)
for version in $versions
do
        [[ $local == 1 ]] && pyenv local $version &> /dev/null
        ~/.pyenv/versions/$version/bin/pip $@
done
[[ $local == 1 ]] && pyenv local $(echo "$versions"|tr '\n' ' ')
