#!/bin/bash
#!! do not use ' Up ' in your strings

httpdVolume="/tmp/docker-volumes/php/"
httpdPort=80
httpdContainerName='apache-php'
phpVersion="7.4-apache"
mysqlVolume="/tmp/docker-volumes/mysql/"
mysqlPort=3306
mysqlContainerName='mysql'
mysqlRootPass="123"
mysqlVersion="latest"

checkDockerRunning () {
	dockerStatus=$(systemctl status docker | grep active)
	if [[ "$dockerStatus" == *"inactive"* || "$dockerStatus" == *"dead"* ]]; then
		systemctl start docker
	fi
}

installDockerImage () {
	if [[ ${#1} -eq 0 ]]; then
		echo 'one param must be sent to installDockerImage function'
		return 1
	fi
	readarray -d : -t temp<<<"$1"
	argLen=${#temp[@]}
	imageName=${temp[0]}
	imageVer=''
	if [[ $argLen == 1 ]]; then
		imageName=${imageName:0:${#imageName}-1}
	else
		imageVer=${temp[1]}
		imageVer=${imageVer:0:${#imageVer}-1}
	fi

	img=$(docker images | grep $imageName)
	if [[ "$img" != *"$imageName"* || ($argLen == 2 && "$img" != *"$imageVer"*) ]]; then
		echo "image $1 not exists, let's pull it:"
		docker pull $1 > /dev/null
	else
		echo "image $1 already exists, no pull is required"
	fi
}

#1:container-name, 2:cmd to run widthout 'docker run --name ...', 3:force 
runDockerImage () {
	if [[ ${#2} == 0 ]]; then
		echo 'two param must be sent to runDockerImage function'
		return 1
	fi
	
	containerStat=$(docker ps --all | grep $1)
	if [[ ${#containerStat} -gt 0 ]]; then
		if [[ $3 == "force" ]]; then
			docker stop $1 > /dev/null
			docker rm $1 > /dev/null
		elif [[ "$containerStat" != *" Up "* ]]; then
			echo "remove container $1"
			docker rm $1 > /dev/null
		else
			echo "container $1 is already running"
			return 0
		fi
	fi
	
	echo "run container $1"
	docker run --name $1 $2 > /dev/null
}

#1:[start,stop,restart]
runDockerContainer () {
	docker $1 $httpdContainerName > /dev/null
	docker $1 $mysqlContainerName > /dev/null
}

help () {
	echo "docker-lamp [install | mysql | start | stop | restart] [options]"
	echo
	echo "install: install php-apache and mysql images and run a container for each of them based of the provided information from the top of this file"
	echo "mysql:   run mysql command line" 
	echo "start:   start httpd and mysql containers"
	echo "stop:    stop httpd and mysql containers"
	echo "restart: restart httpd and mysql containers"
	echo 
	echo "options:"
	echo "--httpd-name: httpd container name"
	echo "--php-ver:    php version. Default is 7.4-apache"
	echo "--httpd-vol:  httpd volume"
	echo "--mysql-name: mysql container name"
	echo "--mysql-ver:  mysql version. Default is latest"
	echo "--mysql-vol:  mysql volume"
	echo "-f, --force:  In case of using install, running container will be removed and created again forcibly"
	echo "-h, --help:   show this help"
	echo
}

abort () {
	echo
	echo '--- help ---------------------------------------'
	help
	exit 1
}

#1:var-name, 2:var-value
setVariable () {
	case $1 in
		'--httpd-name')
			httpdContainerName=$2;;	
		'--php-ver')
			phpVersion=$2;;
		'--mysql-name')
			mysqlContainerName=$2;;
		'--mysql-ver')
			mysqlVersion=$2;;
		'--httpd-vol')
			httpdVolume=$2;;
		'--mysql-vol')
			mysqlVolume=$2;;
	esac
}

cmd=''
force=''
total=$#
while [ $total -gt 0 ]; do
	if [[ $1 == 'install' || $1 == 'mysql' || $1 == 'start' || $1 == 'stop' || $1 == 'restart' ]]; then
		cmd=$1
	elif [[ $1 == '-f' || $1 == '--force' ]]; then
		force='force'
	elif [[ $1 == '-h' || $1 == '--help' ]]; then
		cmd='help'
		break
	elif [[ $1 == '--httpd-name' || $1 == '--php-ver' || $1 == '--mysql-name' || $1 == '--mysql-ver' ]]; then
		setVariable $1 $2
		shift
		((total=$total-1))
	else
		echo "only 'install' and 'mysql' are acceptable as command"
		abort
	fi
	shift
	((total=$total-1))
done
if [[ $cmd == '' ]]; then
	echo "no command detected"
	abort
fi

if [[ $cmd == 'help' ]]; then
	abort
fi

checkDockerRunning

if [[ $cmd == 'install' ]]; then
	#install httpd image
	installDockerImage "php:$phpVersion"
	
	#run httpd under name of php for simplicity
	runDockerImage $httpdContainerName "-d -p $httpdPort:80 --volume=$httpdVolume:/var/www/html php:$phpVersion" $force
	
	#install mysql image
	installDockerImage "mysql/mysql-server:$mysqlVersion"
	
	#run mysql
	runDockerImage $mysqlContainerName "-d -p $mysqlPort:3306 --volume=$mysqlVolume:/var/lib/mysql -e MYSQL_ROOT_PASSWORD=$mysqlRootPass mysql/mysql-server:$mysqlVersion" $force
elif [[ $cmd == 'mysql' ]]; then
	#execute mysql command
	echo "root password is: $mysqlRootPass"
	docker exec -it mysql mysql -u root -p
elif [[  $cmd == 'start' || $cmd == 'stop' || $cmd == 'restart' ]]; then
	echo "$cmd httpd & mysql"
	runDockerContainer $cmd
fi
