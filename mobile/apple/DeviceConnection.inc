// Pairing is complete only when the user can see the granted remote locations.
- (void)presentApproval:(UIAlertController *)alert deadline:(NSDate *)deadline expired:(dispatch_block_t)expired {
    if(!self.view.window||[deadline timeIntervalSinceNow]<=0){expired();return;}
    if(self.presentedViewController||self.isBeingDismissed){dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{[self presentApproval:alert deadline:deadline expired:expired];});return;}
    if(self.pairingStatus)self.pairingStatus.text=T(@"Confirm the same verification on both devices.");
    [self presentViewController:alert animated:YES completion:nil];
}
- (void)beginPairing:(NSString *)invitation host:(NSString *)host port:(NSNumber *)port code:(NSString *)code {
    if(self.pairing)return;self.pairing=YES;[self clear:@"connecting"];
    [self.content addArrangedSubview:[self label:T(@"Connecting your devices") size:28]];
    self.pairingStatus=[self label:T(@"Connecting securely… Confirm pairing on the other device when asked.") size:17];[self.content addArrangedSubview:self.pairingStatus];
    UIActivityIndicatorView *spinner=[[UIActivityIndicatorView alloc]initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium];[spinner startAnimating];[self.content addArrangedSubview:spinner];
    [self.content addArrangedSubview:[self label:T(@"The QR already contains the address and code. You do not need to enter them again. Keep both apps open.") size:15]];
    [self call:@"pair" args:@[invitation,host,port,code] then:^(NSString *json){self.pairing=NO;[self updateState:json];NSString *identity=self.state[@"pairedDevice"];if(identity.length)[self openDevice:identity];else [self showDevices];}];
}
- (void)openDevice:(NSString *)identity { [self openDevice:identity retry:YES]; }
- (void)openDevice:(NSString *)identity retry:(BOOL)retry {
    [self clear:@"connecting"];[self.content addArrangedSubview:[self label:T(@"Checking shared folders…") size:22]];
    [self call:@"connection_status" args:@[identity] then:^(NSString *json){NSDictionary *value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
        if([value[@"status"] isEqual:@"ready"]){self.peer=identity;self.path=@"/";self.filter=@"";[self.selection removeAllObjects];[self showFiles];return;}
        if([value[@"status"] isEqual:@"unavailable"]&&retry){
            // The device may have a new network address: find it again by its identity, then retry once.
            for(NSNetService *service in self.services)[service resolveWithTimeout:3];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(2*NSEC_PER_SEC)),dispatch_get_main_queue(),^{
                NSDictionary *found=nil;for(NSDictionary *device in self.nearby.allValues)if([device[@"id"] isEqual:identity])found=device;
                if(!found){[self openDevice:identity retry:NO];return;}
                [self call:@"reconnect" args:@[identity,found[@"host"],found[@"port"]] then:^(NSString *state){[self updateState:state];[self openDevice:identity retry:NO];}];});
            return;}
        NSString *status=value[@"status"],*name=value[@"name"]?:@"";
        [self clear:@"connection-status"];self.statusPeer=identity;
        [self screenTitle:name back:T(@"Devices") action:^{[self showNearby];}];
        if([status isEqual:@"not_recognized"]){
            // The other device removed or replaced this pairing: the only fix is a new pairing.
            [self section:T(@"Pair this device again") rows:@[
                [self row:T(@"Remove and pair again") detail:nil symbol:@"arrow.triangle.2.circlepath" tint:Accent() action:^{[self removePairing:identity name:name pairAgain:YES];}]]
                footer:T(@"The other device no longer knows this iPhone, for example because the pairing was removed there. Remove the old pairing here and pair again with a new code. Files on both devices stay.")];
            return;}
        BOOL empty=[status isEqual:@"no_shared_folders"];
        [self section:T(empty?@"Paired · choose what to share":@"Device is currently unavailable") rows:@[
            [self row:T(@"Check again") detail:nil symbol:@"arrow.clockwise" tint:UIColor.systemBlueColor action:^{[self openDevice:identity];}]]
            footer:T(empty?@"The devices are paired, but the other device has not shared any folders with this iPhone yet. On your Mac, open Soovee Transfers → Shared folders, choose this iPhone and click Share folder…. Then tap Check again.":@"Keep Soovee open on both devices and connect them to the same local network. A paired iPhone cannot serve its files while iOS suspends the app in the background.")];
        [self section:nil rows:@[[self row:T(@"Remove pairing") detail:nil symbol:nil tint:UIColor.systemRedColor value:nil chevron:NO menu:nil action:^{[self removePairing:identity name:name pairAgain:NO];}]] footer:nil];
        if(empty){
            // A folder is often shared a moment after pairing: look again by itself while this screen is open.
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(4*NSEC_PER_SEC)),dispatch_get_main_queue(),^{
                if(![self.screen isEqual:@"connection-status"]||![self.statusPeer isEqual:identity]||self.presentedViewController)return;
                [self call:@"connection_status" args:@[identity] then:^(NSString *again){NSDictionary *next=[NSJSONSerialization JSONObjectWithData:[again dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
                    if([self.screen isEqual:@"connection-status"]&&[self.statusPeer isEqual:identity]&&[next[@"status"] isEqual:@"ready"])[self openDevice:identity];}];});
        }
    }];
}
#if !TARGET_OS_TV
- (void)addFolder {
    self.choosingFolder=YES;UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc]initForOpeningContentTypes:@[UTTypeFolder] asCopy:NO];picker.delegate=self;picker.allowsMultipleSelection=NO;
    [self presentViewController:picker animated:YES completion:nil];
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)picker { self.choosingFolder=NO; }
- (void)restoreFolders {
    for(NSDictionary *value in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"]){NSData *bookmark=[[NSData alloc]initWithBase64EncodedString:value[@"bookmark"] options:0];BOOL stale=NO;NSError *error=nil;NSURL *url=[NSURL URLByResolvingBookmarkData:bookmark options:NSURLBookmarkResolutionWithoutUI relativeToURL:nil bookmarkDataIsStale:&stale error:&error];
        if(url&&[url startAccessingSecurityScopedResource]){NSNumber *directory=nil;[url getResourceValue:&directory forKey:NSURLIsDirectoryKey error:nil];if(directory.boolValue)self.folderAccess[value[@"key"]]=url;else [url stopAccessingSecurityScopedResource];}
    }
}
- (void)retainFolder:(NSURL *)url {
    if(![url startAccessingSecurityScopedResource]){[self showError:T(@"This folder is not accessible. Choose it again in Files.")];return;}
    NSError *error=nil;NSData *bookmark=[url bookmarkDataWithOptions:NSURLBookmarkCreationMinimalBookmark includingResourceValuesForKeys:nil relativeToURL:nil error:&error];
    if(!bookmark){[url stopAccessingSecurityScopedResource];[self showError:error.localizedDescription];return;}
    NSMutableArray *folders=[[[NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"]?:@[] mutableCopy] mutableCopy];
    for(NSDictionary *existing in folders){NSURL *old=self.folderAccess[existing[@"key"]];if([old.path isEqual:url.path]){[url stopAccessingSecurityScopedResource];self.peer=@"";self.path=[@"/" stringByAppendingString:existing[@"name"]];[self showFiles];return;}}
    NSString *name=nil;[url getResourceValue:&name forKey:NSURLLocalizedNameKey error:nil];if(!name.length)name=url.lastPathComponent;NSCharacterSet *invalid=[NSCharacterSet characterSetWithCharactersInString:@"/\\:*?\"<>|"];name=[[name componentsSeparatedByCharactersInSet:invalid] componentsJoinedByString:@"-"];name=[name stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];if(!name.length||[name isEqual:@"."]||[name isEqual:@".."])name=@"Folder";
    NSMutableSet *names=[NSMutableSet setWithObject:@"shared"];for(NSDictionary *existing in folders)[names addObject:[existing[@"name"] lowercaseString]];NSString *base=name;NSInteger number=2;while([names containsObject:name.lowercaseString])name=[NSString stringWithFormat:@"%@ (%ld)",base,(long)number++];
    NSString *key=NSUUID.UUID.UUIDString;[folders addObject:@{@"key":key,@"name":name,@"bookmark":[bookmark base64EncodedStringWithOptions:0],@"shared":@NO}];self.folderAccess[key]=url;
    [NSUserDefaults.standardUserDefaults setObject:folders forKey:@"folderBookmarks"];
    [self configureFolders:^{self.peer=@"";self.path=[@"/" stringByAppendingString:name];[self showFiles];}];
}
- (void)configureFolders:(dispatch_block_t)complete {
    NSMutableArray *roots=[NSMutableArray arrayWithObject:@{@"key":@"app",@"name":@"Shared",@"path":self.state[@"folder"]?:@"",@"writable":@YES}];BOOL sharing=NO;
    for(NSDictionary *value in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"]){NSURL *url=self.folderAccess[value[@"key"]];if(!url)continue;BOOL shared=[value[@"shared"] boolValue];sharing|=shared;[roots addObject:@{@"key":value[@"key"],@"name":value[@"name"],@"path":url.path,@"writable":@YES,@"shared":@(shared)}];}
    NSString *json=[[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:roots options:0 error:nil] encoding:NSUTF8StringEncoding];[self call:@"configure_storage" args:@[json,@(sharing)] then:^(NSString *value){[self updateState:value];complete();}];
}
- (void)manageFolders {
    UIAlertController *list=[UIAlertController alertControllerWithTitle:T(@"Folder access and sharing") message:T(@"Added folders are private to this iPhone until you explicitly share them. You can revoke access without deleting files.") preferredStyle:UIAlertControllerStyleAlert];
    for(NSDictionary *value in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"])[list addAction:[UIAlertAction actionWithTitle:value[@"name"] style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){
        BOOL shared=[value[@"shared"] boolValue];UIAlertController *options=[UIAlertController alertControllerWithTitle:value[@"name"] message:T(shared?@"This folder is shared with approved paired devices.":@"Only this iPhone can browse this folder in Soovee.") preferredStyle:UIAlertControllerStyleAlert];
        [options addAction:[UIAlertAction actionWithTitle:T(shared?@"Stop sharing this folder":@"Share with paired devices") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){
            UIAlertController *confirm=[UIAlertController alertControllerWithTitle:T(shared?@"Stop sharing this folder":@"Share with paired devices") message:T(shared?@"Paired devices will lose access. Files stay on this iPhone.":@"Allow all currently approved paired devices to browse, copy, rename and delete files in this folder? Keep Soovee open while using it remotely.") preferredStyle:UIAlertControllerStyleAlert];[confirm addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[confirm addAction:[UIAlertAction actionWithTitle:T(@"Apply") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){NSMutableArray *items=[NSMutableArray new];for(NSDictionary *item in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"]){NSMutableDictionary *updated=[item mutableCopy];if([item[@"key"] isEqual:value[@"key"]])updated[@"shared"]=@(!shared);[items addObject:updated];}[NSUserDefaults.standardUserDefaults setObject:items forKey:@"folderBookmarks"];[self configureFolders:^{[self showHome];}];}]];[self presentViewController:confirm animated:YES completion:nil];}]];
        [options addAction:[UIAlertAction actionWithTitle:T(@"Remove location · keep files") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){NSMutableArray *items=[NSMutableArray new];for(NSDictionary *item in [NSUserDefaults.standardUserDefaults arrayForKey:@"folderBookmarks"])if(![item[@"key"] isEqual:value[@"key"]])[items addObject:item];[NSUserDefaults.standardUserDefaults setObject:items forKey:@"folderBookmarks"];NSURL *url=self.folderAccess[value[@"key"]];[self.folderAccess removeObjectForKey:value[@"key"]];[self configureFolders:^{[url stopAccessingSecurityScopedResource];[self showHome];}];}]];
        [options addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:options animated:YES completion:nil];
    }]];
    [list addAction:[UIAlertAction actionWithTitle:T(@"Add folder from Files…") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self addFolder];}]];[list addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:list animated:YES completion:nil];
}
#else
- (void)restoreFolders {}
- (void)configureFolders:(dispatch_block_t)complete {complete();}
- (void)addFolder {}
#endif
