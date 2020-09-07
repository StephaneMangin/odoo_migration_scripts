#!/bin/bash

#
# This scripts aims to help project update locally
#
#                        +------------------+     +-----------------+
#                  +-----| select database  +-----+has purge option?|
#                  |     +------------------+     +----+------+-----+
#                  |                                   |      |
#                  |     +------------------+      yes |    no|
#                  |     |                  <----------+      |
#                  |     | purge local files|                 |
#                  |     |                  +----------+      |
#                  |     +--------+---------+          |      |
#                  +-----------------------------------+      |
#                                                 +----v------v-----+
#  +-----------------+   +------------------+ yes | database file   |
#  |restore template | no|                  <-----+ exists locally  |
#  |                 <---+ template exists? |     | in cache?       |
#  +-------+--^------+   |                  <--+  +--------+--------+
#          |  |          +------------------+  |         no|
#          |  |                   |yes         |           |
#          |  |      yes +--------v---------+  |           |
#          |  +----------+                  |  |  +--------v--------+
#          |             | is cache renew?  |  +--+retrieve database|
#          +------------->                  |     +-----------------+
#                        +------------------+
#                                 |no
#                        +--------v---------+
#                        + restore database |
#                        +------------------+


################################################################################
# Constants
################################################################################
PROJECT_NAME=$(basename $PWD)
CACHE_FOLDER=~/.cache/camptocamp
AWS_BUCKET_NAME=odoo-dumps
PG_DB_TEMPLATE=odoodb_template
PG_DB_SAMPLE=odoodb_sample
LOG_FILE=project_restore.log
CONFIG_FILE=config.yaml
MIGRATION_LOG_FILE=database_migration.log
ERROR_JSON=database_migration_errors.json
MODULES_JSON=database_migration_modules.json
ODOO_MIGRATED_DB_URL="https://upgrade.odoo.com/database/eu1/"
ODOO_POSTFIX_URL="/upgraded/archive"
ODOO_IP=localhost
ODOO_PORT=8069
GPG_IDENTITY=3E84782B5BC3B642

################################################################################
# Variables
################################################################################
TEMPLATE_TO_UPDATE=0 # Force database template update
PARTIAL_TEMPLATE_RESTORE=0 # an error has occured during template restore
PURGE=0 # force cache purge
ODOO_MIGRATION_IDS= # values from odoo migration url
CLEAN_AFTER_EXIT=0 # Do not remove logs and deciphered database
DB_FOLDER="$CACHE_FOLDER/databases/$PROJECT_NAME" # variates with database from odoo
FORCE_BUILD=0 # force the reconfigure and build of project and docker image
RESTORE_DATABASE=0 # force database restore from template

################################################################################
# Cleaning functions
################################################################################

function clean() {
  if [[ $CLEAN_AFTER_EXIT == 1 ]]; then
    rm -Rf $DB_FOLDER/*.pg &>/dev/null
    rm -Rf $DB_FOLDER/*.sql &>/dev/null
  fi
  if [[ $PARTIAL_TEMPLATE_RESTORE == 1 ]]; then
    docker-compose run --rm odoo dropdb $PG_DB_TEMPLATE &>/dev/null
  fi
}

function purge() {
  log "Purge configuration, databases and logs..."
  docker-compose run --rm odoo dropdb odoodb &> /dev/null
  docker-compose run --rm odoo dropdb $PG_DB_TEMPLATE &> /dev/null
  rm -Rf $DB_FOLDER &> /dev/null
  rm -Rf $LOG_FILE $ERROR_JSON $MODULES_JSON &> /dev/null
}

################################################################################
# SIG exception management
################################################################################

function clean_and_exit() {
  clean
  kill -HUP 0
  exit 0
}

trap clean_and_exit INT
trap clean_and_exit SIGINT
trap clean_and_exit EXIT

################################################################################
# Log formatting
################################################################################

function log() {
  echo -e "$(date '+%F %T') INFO \e[1m\e[34m$*\e[0m" |& tee -a $LOG_FILE
}

################################################################################
# Docker hooks
################################################################################
function docker_post_build() {
  for file in $(find . -name "Dockerfile")
  do
      sed -i "/^### DO NOT PUSH/,/^### END DO NOT PUSH/d" $file
      git add $file
  done
}

function docker_pre_build() {
  readonly repo=$(git rev-parse --show-toplevel)
  COMMANDS_START="### DO NOT PUSH ###"
  COMMANDS_APT="RUN echo 'Acquire::http::Proxy \"http://192.168.1.22:8000\";' > /etc/apt/apt.conf.d/00proxy"
  COMMANDS_MKDIR_ROOT="RUN mkdir -p /root/.pip"
  COMMANDS_MKDIR_ODOO="RUN mkdir -p /home/odoo/.pip"
  COMMANDS_PIP="RUN echo '[global]\ntimeout = 30\ntrusted-host = 192.168.1.22\nindex-url = http://192.168.1.22:8247/simple' | tee /home/odoo/.pip/pip.conf /root/.pip/pip.conf"
  COMMANDS_END="### END DO NOT PUSH ###
  "

  for file in $(find . -name "Dockerfile")
  do
      echo "Found a Dockerfile $file"
      sed -i "/^### DO NOT PUSH/,/^### END DO NOT PUSH/d" $file
      if grep -q "apt-get install" "$file"; then
          sed '/^LABEL\|MAINTAINER/r'<(
            echo $COMMANDS_START
            echo $COMMANDS_APT
            #echo $COMMANDS_MKDIR_ROOT
            #echo $COMMANDS_MKDIR_ODOO
            #echo $COMMANDS_PIP
            echo $COMMANDS_END
          ) -i $file
          echo "Done"
      fi
  done
}

################################################################################
# Functional methods
################################################################################

function yaml() {
  pip install pyaml &>/dev/null
  eval "$2=$(python -c "import yaml;print(yaml.safe_load(open('$1'))['$2'])")"
}

function db_name_user_input() {
  echo "--------------------------------------------------------------------------------"
  echo " Select a database to proceed:"
  echo "--------------------------------------------------------------------------------"
  names=(exit $(aws --profile odoo-dumps s3 ls s3://odoo-dumps/ | sort | awk '{print $2}' | rev | cut -c2- | rev))
  names+=( "no_name" )
  select name in "${names[@]}"; do
    [[ $name == "exit" ]] || [[ -z $name ]] && exit 0
    PG_PROD_DBNAME="$name"
    if [[ -n $ODOO_MIGRATION_IDS ]]; then
      PG_PROD_DBNAME="upgraded_$name"
    fi
    log "database '$name' selected, proceeding..." |& tee -a $LOG_FILE
    return 0
  done
}

function _get_last_db_files_from_aws() {
  PG_DB_FILENAME=$(aws --profile odoo-dumps s3 ls s3://$AWS_BUCKET_NAME/$PG_PROD_DBNAME/ | sort -r | head -n 1 | awk '{print $4}')
}

function _get_last_db_files_from_local() {
  current_pg_filename=$(ls $DB_FOLDER | sort -r | grep "^$PG_PROD_DBNAME.*\.gpg$" | head -n 1)
  [[ -n $current_pg_filename ]] && [[ $current_pg_filename == $PG_DB_FILENAME ]] && log "Found a database to use : $DB_FOLDER/$PG_DB_FILENAME"
}

function retrieve_client_database() {
  [[ ! -d $DB_FOLDER ]] && mkdir -p "$DB_FOLDER"

  _get_last_db_files_from_local
  [[ -z $PG_DB_FILENAME ]] && _get_last_db_files_from_aws

  if [[ ! -f $DB_FOLDER/$PG_DB_FILENAME ]]; then
    if [[ -n $ODOO_MIGRATION_IDS ]]; then
      tmpfile=$(mktemp /tmp/odoo_migrated_database.XXXXX.zip)
      database_to_retrieve=$ODOO_MIGRATED_DB_URL$ODOO_MIGRATION_IDS$ODOO_POSTFIX_URL
      log "Retrieving database from Odoo : '$database_to_retrieve'"
      wget -q --show-progress --output-document "$tmpfile" "$database_to_retrieve"
      if [[ ! -f $DB_FOLDER/$PG_DB_FILENAME ]]; then
        log "Unzipping '$tmpfile' to local cache"
        unzip -q "$tmpfile" -d "$DB_FOLDER" |& tee -a $LOG_FILE
        mv "$DB_FOLDER/dump.sql" "$DB_FOLDER/$PG_PROD_DBNAME.sql" &> /dev/null
        rm "$DB_FOLDER/$PG_DB_FILENAME"  &>/dev/null
        PG_DB_FILENAME="$PG_PROD_DBNAME.sql.gpg"
        gpg -e -r $GPG_IDENTITY "$DB_FOLDER/$PG_PROD_DBNAME.sql" |& tee -a $LOG_FILE
      fi
    else
      aws_url="s3://odoo-dumps/$PG_PROD_DBNAME/$PG_DB_FILENAME"
      log "Retrieve database from AWS : $aws_url"
      aws --profile=odoo-dumps s3 cp $aws_url "$DB_FOLDER" |& tee -a $LOG_FILE
    fi
    TEMPLATE_TO_UPDATE=1
  fi
  tmp_pg_filename=$(echo "$PG_DB_FILENAME" | sed -e 's/\.gpg//')
  if [[ ! -f $DB_FOLDER/$tmp_pg_filename ]]; then
    log "Deciphering database"
    gpg "$DB_FOLDER/$PG_DB_FILENAME" |& tee -a $LOG_FILE |& tee -a $LOG_FILE
  fi
  PG_DB_FILENAME=$tmp_pg_filename
}

function restore_database() {
  [[ $TEMPLATE_TO_UPDATE == 1 ]] && log "Client database updated. Forcing template update."
  if [[ $TEMPLATE_TO_UPDATE == 1 ]] || [[ $(docker exec -it $DB_CONTAINER_NAME psql -U odoo -lqt | grep -c $PG_DB_TEMPLATE) != 1 ]]; then
    docker-compose run --rm odoo dropdb $PG_DB_TEMPLATE &>/dev/null
    docker-compose run --rm odoo createdb $PG_DB_TEMPLATE &>/dev/null
    PARTIAL_TEMPLATE_RESTORE=1
    if [[ $PG_DB_FILENAME =~ \.sql$ ]]; then
      log "Restoring template from sql..."
      PGPASSWORD=odoo psql -h localhost -p $DB_CONTAINER_PORT -d $PG_DB_TEMPLATE -U odoo -f $DB_FOLDER/$PG_DB_FILENAME |& tee -a $LOG_FILE
    else
      log "Restoring template from pg..."
      PGPASSWORD=odoo pg_restore --no-privileges --no-owner -h localhost -p $DB_CONTAINER_PORT -U odoo -d $PG_DB_TEMPLATE $DB_FOLDER/$PG_DB_FILENAME |& tee -a $LOG_FILE
    fi
    PARTIAL_TEMPLATE_RESTORE=0
  fi
  if [[ $RESTORE_DATABASE == 1 ]]; then
    log "Restoring database from template..."
    docker-compose run --rm odoo dropdb odoodb &>/dev/null
    docker-compose run --rm odoo createdb -T $PG_DB_TEMPLATE odoodb |& tee -a $LOG_FILE
  fi
}

#function migrate() {
#  log "Starting database migration... (see $MIGRATION_LOG_FILE for details)"
#  docker-compose run --rm -e MARABUNTA_MODE=migration -e DB_NAME=odoodb odoo rundatabasemigration |& tee -a $MIGRATION_LOG_FILE
#
#  echo "Checking errors and modules..." |& tee -a $MIGRATION_LOG_FILE
#  docker-compose run --rm -e DB_NAME=$PG_DB_SAMPLE -e MARABUNTA_MODE=sample odoo odoo --stop-after-init |& tee -a $MIGRATION_LOG_FILE
#  parse_migration_log.py $MIGRATION_LOG_FILE > $ERROR_JSON
#  invoke migrate.check-modules odoodb $PG_DB_TEMPLATE $PG_DB_SAMPLE > $MODULES_JSON
#
#  docker-compose down |& tee -a $MIGRATION_LOG_FILE
#}

function configure_project() {
  image=$(docker images -q "$PROJECT_NAME"_odoo:latest 2> /dev/null)
  if [[ $FORCE_BUILD == 1 ]] || [[ -z $image ]]; then
    log "Configure project..."
    [[ -f tasks/requirements.txt ]] && pip install -r tasks/requirements.txt
    [[ -f odoo/dev_requirements.txt ]] && pip install -r odoo/dev_requirements.txt
    invoke submodule.init |& tee -a $LOG_FILE
    invoke submodule.update |& tee -a $LOG_FILE
    docker_pre_build
    docker-compose build
    docker_post_build
  fi
}

function restore_db_container() {
  docker-compose stop db
  # Get the docker container name of the database
  DB_CONTAINER_NAME=$(docker-compose ps | grep "db" | awk '{print $1}')
  if [[ -z $DB_CONTAINER_NAME ]]; then
    DB_VOLUME_NAME=$(docker inspect --format '{{range .Mounts}}{{.Name}} {{end}}' "$DB_CONTAINER_NAME")
    [[ -n $DB_VOLUME_NAME ]] && docker volume rm $DB_VOLUME_NAME
  fi
  docker-compose up -d db
  until [[ $(docker inspect -f {{.State.Running}} "$DB_CONTAINER_NAME") == "true" ]]; do
      sleep 3;
  done;

  # Get the docker container port of the database
  DB_CONTAINER_PORT=$(docker-compose ps | grep "$DB_CONTAINER_NAME" | awk '{print $7}' | cut -d'-' -f1 | cut -d':' -f2)
}

function prepare() {
  rm -Rf $LOG_FILE $ERROR_JSON $MODULES_JSON &>/dev/null
  log "Cache folder for this project : $DB_FOLDER" |& tee -a $LOG_FILE
  if [[ -n $ODOO_MIGRATION_IDS ]]; then
    DB_FOLDER="$DB_FOLDER/migrated_from_odoo"
    PG_PROD_DBNAME="upgraded_$PG_PROD_DBNAME"
  fi
  [[ ! -d $DB_FOLDER ]] && mkdir -p "$DB_FOLDER"
}

function load_config() {

  [[ ! -d $DB_FOLDER ]] && mkdir -p $DB_FOLDER
  [[ ! -f $LOG_FILE ]] && touch $LOG_FILE

  if [[ -f $DB_FOLDER/$CONFIG_FILE ]]; then
    pip install pyaml &>/dev/null
    yaml "$DB_FOLDER/$CONFIG_FILE" "AWS_BUCKET_NAME"
    yaml "$DB_FOLDER/$CONFIG_FILE" "PG_DB_TEMPLATE"
    yaml "$DB_FOLDER/$CONFIG_FILE" "PG_DB_SAMPLE"
    yaml "$DB_FOLDER/$CONFIG_FILE" "LOG_FILE"
    yaml "$DB_FOLDER/$CONFIG_FILE" "MIGRATION_LOG_FILE"
    yaml "$DB_FOLDER/$CONFIG_FILE" "ERROR_JSON"
    yaml "$DB_FOLDER/$CONFIG_FILE" "MODULES_JSON"
    yaml "$DB_FOLDER/$CONFIG_FILE" "ODOO_MIGRATED_DB_URL"
    yaml "$DB_FOLDER/$CONFIG_FILE" "ODOO_POSTFIX_URL"
    yaml "$DB_FOLDER/$CONFIG_FILE" "ODOO_IP"
    yaml "$DB_FOLDER/$CONFIG_FILE" "ODOO_PORT"
    yaml "$DB_FOLDER/$CONFIG_FILE" "GPG_IDENTITY"
    yaml "$DB_FOLDER/$CONFIG_FILE" "PG_PROD_DBNAME"
    yaml "$DB_FOLDER/$CONFIG_FILE" "CLEAN_AFTER_EXIT"
    yaml "$DB_FOLDER/$CONFIG_FILE" "RESTORE_DATABASE"
  fi
  [[ $CLEAN_AFTER_EXIT == 1 ]] && log "/!\ clean after exit option activated" |& tee -a $LOG_FILE
  if [[ -z $PG_PROD_DBNAME ]]; then
    db_name_user_input
  else
    log "/!\ database '$PG_PROD_DBNAME' selected" |& tee -a $LOG_FILE
  fi
}

function save_config() {
    rm "$DB_FOLDER/$CONFIG_FILE"
    cat << EOF >> "$DB_FOLDER/$CONFIG_FILE"
AWS_BUCKET_NAME: $AWS_BUCKET_NAME
PG_DB_TEMPLATE: $PG_DB_TEMPLATE
PG_DB_SAMPLE: $PG_DB_SAMPLE
LOG_FILE: $LOG_FILE
MIGRATION_LOG_FILE: $MIGRATION_LOG_FILE
ERROR_JSON: $ERROR_JSON
MODULES_JSON: $MODULES_JSON
ODOO_MIGRATED_DB_URL: $ODOO_MIGRATED_DB_URL
ODOO_POSTFIX_URL: $ODOO_POSTFIX_URL
ODOO_IP: $ODOO_IP
ODOO_PORT: $ODOO_PORT
GPG_IDENTITY: $GPG_IDENTITY
PG_PROD_DBNAME: $PG_PROD_DBNAME
CLEAN_AFTER_EXIT: $CLEAN_AFTER_EXIT
RESTORE_DATABASE: $RESTORE_DATABASE
EOF
}

################################################################################
# Arg parser
################################################################################
function usage {
    echo "usage: $0 [-m|--migrate] [-p|--purge]"
    echo "  -p|--purge                  purge local file cache and databases" \
                                        "for this project"
    echo "  -n|--no-clean               Don't clean *.pg and *.sql files at end"
    echo "  -r|--restore-database       Force database restore from template"
    echo "  -f|--force-build            Force the build of the docker image"
    echo "  -o|--from-odoo-migration    If database comes from odoo," \
                                        "indicates the ids as follow id/key" \
                                        "(i.e. 12345/IRHvI20ZLj'uwzFzAYAVWg==)"
    exit 1
}


load_config

while [[ "$#" -gt 0 ]]; do
  case $1 in
  -o|--from-odoo-migration)
    if [[ -n $2 ]] && [[ ${2:0:1} != "-" ]] && [[ $2 =~ "/" ]]; then
      ODOO_MIGRATION_IDS=$2
      shift
    else
      echo "Error: Argument for $1 is missing" >&2
      exit 1
    fi
    ;;
  -r|--restore-database)
    RESTORE_DATABASE=1
    ;;
  -p|--purge)
    PURGE=1
    RESTORE_DATABASE=1
    ;;
  -c|--clean)
    CLEAN_AFTER_EXIT=1
    ;;
  -f|--force-build)
    FORCE_BUILD=1
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown parameter passed: $1"
    exit 1
    ;;
  esac
  shift
done
save_config
log "Actual configuration : \n$(cat "$DB_FOLDER/$CONFIG_FILE")"

[[ $PURGE == 1 ]] && purge
prepare
configure_project
if [[ $RESTORE_DATABASE == 1 ]]; then
  if [[ $PURGE == 1 ]]; then
    restore_db_container
    retrieve_client_database
  fi
  restore_database
fi

exit 0
