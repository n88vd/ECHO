update storage.buckets
   set allowed_mime_types = array['audio/ogg', 'audio/opus', 'audio/webm', 'audio/wav', 'audio/x-wav', 'audio/mpeg']
 where id = 'echo-audio';
