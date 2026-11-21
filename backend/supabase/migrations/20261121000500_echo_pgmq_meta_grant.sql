grant select on pgmq.meta to echo_service;
select pgmq.purge_queue('echo_purge');
