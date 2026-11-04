// Native file-manager presentation. Included inside SooveeViewController.
- (UIButton *)card:(NSString *)title detail:(NSString *)detail symbol:(NSString *)symbol action:(dispatch_block_t)action {
    UIButton *button=[self button:title action:action];UIButtonConfiguration *cfg=button.configuration;
    cfg.subtitle=detail;cfg.image=[[UIImage systemImageNamed:symbol] imageWithTintColor:Accent() renderingMode:UIImageRenderingModeAlwaysOriginal];cfg.imagePadding=14;cfg.preferredSymbolConfigurationForImage=[UIImageSymbolConfiguration configurationWithPointSize:27 weight:UIImageSymbolWeightRegular];
    cfg.titleTextAttributesTransformer=^NSDictionary *(NSDictionary *attributes){NSMutableDictionary *result=[attributes mutableCopy];result[NSFontAttributeName]=[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold];return result;};
    cfg.subtitleTextAttributesTransformer=^NSDictionary *(NSDictionary *attributes){NSMutableDictionary *result=[attributes mutableCopy];result[NSFontAttributeName]=[UIFont systemFontOfSize:12];result[NSForegroundColorAttributeName]=UIColor.secondaryLabelColor;return result;};button.configuration=cfg;return button;
}
#if TARGET_OS_TV
- (void)showHome {
    [self clear:@"home"];[self.content addArrangedSubview:[self label:T(TARGET_OS_TV?@"TV library":@"Overview") size:32]];
    [self.content addArrangedSubview:[self label:T(@"Your files. All your devices.") size:16]];
    NSArray *volumes=self.state[@"storage"]?:@[];
    for(NSDictionary *volume in volumes){NSString *name=volume[@"name"]?:@"Shared";NSString *capacity=[NSString stringWithFormat:@"%@ %@ · %@ %@",T(@"Free"),[NSByteCountFormatter stringFromByteCount:[volume[@"free"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile],T(@"Total"),[NSByteCountFormatter stringFromByteCount:[volume[@"total"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile]];
        [self.content addArrangedSubview:[self card:T(name) detail:capacity symbol:@"internaldrive" action:^{self.peer=@"";self.path=[@"/" stringByAppendingString:name];self.filter=@"";[self.selection removeAllObjects];[self showFiles];}]];
        UIProgressView *meter=[[UIProgressView alloc]initWithProgressViewStyle:UIProgressViewStyleDefault];meter.progressTintColor=Accent();double total=[volume[@"total"] doubleValue];meter.progress=total>0?1-[volume[@"free"] doubleValue]/total:0;[self.content addArrangedSubview:meter];
    }
    [self.content addArrangedSubview:[self label:T(@"Your devices") size:21]];
    for(NSDictionary *device in self.state[@"peers"]){[self.content addArrangedSubview:[self card:device[@"name"] detail:T(@"Paired · open") symbol:@"desktopcomputer" action:^{[self openDevice:device[@"id"]];}]];}
    [self.content addArrangedSubview:[self card:T(@"Find a device or scan QR") detail:T(@"On your local network") symbol:@"qrcode.viewfinder" action:^{[self showNearby];}]];
#if !TARGET_OS_TV
    [self.content addArrangedSubview:[self card:T(@"Add folder from Files…") detail:T(@"On My iPhone, iCloud Drive and available document providers") symbol:@"folder.badge.plus" action:^{[self addFolder];}]];
    [self.content addArrangedSubview:[self card:T(@"Import files…") detail:T(@"Choose files using the iPhone document picker") symbol:@"square.and.arrow.down" action:^{UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc]initForOpeningContentTypes:@[UTTypeItem] asCopy:YES];picker.allowsMultipleSelection=YES;picker.delegate=self;[self presentViewController:picker animated:YES completion:nil];}]];
#endif
}
- (void)showTransfers {
    [self clear:@"transfers"];[self.content addArrangedSubview:[self label:T(@"Transfers") size:30]];
    [self call:@"operation_snapshot" args:@[] then:^(NSString *json){if(![self.screen isEqual:@"transfers"])return;NSDictionary *value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];NSString *details=value.count?[NSString stringWithFormat:@"%@\n%@\n%@\n%@ / %@ · %@",T(value[@"status"]?:@""),value[@"current"]?:@"",value[@"destination"]?:@"",value[@"completed"]?:@0,value[@"files"]?:@0,[NSByteCountFormatter stringFromByteCount:[value[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile]]:T(@"No transfers yet.");[self.content addArrangedSubview:[self label:details size:17]];[self add:T(@"Diagnostic log") action:^{[self showLog];}];}];
}
#endif
- (NSString *)itemPath:(NSDictionary *)item {return [self.path stringByAppendingPathComponent:item[@"name"]];}
- (NSString *)itemSymbol:(NSDictionary *)item {
    if([item[@"directory"] boolValue])return @"folder.fill";
    NSString *extension=[item[@"name"] pathExtension].lowercaseString;
    if([@[@"jpg",@"jpeg",@"png",@"heic",@"webp"] containsObject:extension])return @"photo";
    if([@[@"mp4",@"mkv",@"mov",@"avi"] containsObject:extension])return @"film";
    if([@[@"zip",@"rar",@"7z",@"tar",@"gz"] containsObject:extension])return @"archivebox";
    if([@[@"mp3",@"flac",@"m4a",@"wav"] containsObject:extension])return @"music.note";
    return @"doc.text";
}
// Compact symbol buttons keep the folder toolbar on one line in every language;
// the spoken label stays available to VoiceOver and as the long-press title.
- (UIButton *)tool:(NSString *)symbol label:(NSString *)label action:(dispatch_block_t)action {
    UIButton *button=[self button:label action:action];UIButtonConfiguration *configuration=button.configuration;
    configuration.title=nil;configuration.image=[UIImage systemImageNamed:symbol];configuration.preferredSymbolConfigurationForImage=[UIImageSymbolConfiguration configurationWithPointSize:17 weight:UIImageSymbolWeightSemibold];
    button.configuration=configuration;button.accessibilityLabel=label;return button;
}
#if TARGET_OS_TV
- (void)renderFiles {
    [self clear:@"files"];NSString *path=self.path;
    NSString *device=T(@"This device");for(NSDictionary *peer in self.state[@"peers"])if([peer[@"id"] isEqual:self.peer])device=peer[@"name"];
    [self.content addArrangedSubview:[self label:[path isEqual:@"/"]?T(@"Files"):path.lastPathComponent size:28]];
    UILabel *location=[self label:[NSString stringWithFormat:@"%@ · %@",device,path] size:13];location.textColor=UIColor.secondaryLabelColor;[self.content addArrangedSubview:location];
    UIStackView *tools=[UIStackView new];tools.axis=UILayoutConstraintAxisHorizontal;tools.distribution=UIStackViewDistributionFillEqually;tools.spacing=5;
    if(![path isEqual:@"/"])[tools addArrangedSubview:[self tool:@"arrow.up" label:T(@"Parent folder") action:^{self.path=path.stringByDeletingLastPathComponent;self.filter=@"";[self.selection removeAllObjects];[self showFiles];}]];
    [tools addArrangedSubview:[self tool:@"line.3.horizontal.decrease" label:T(@"Filter") action:^{UIAlertController *filter=[UIAlertController alertControllerWithTitle:T(@"Filter this folder") message:nil preferredStyle:UIAlertControllerStyleAlert];[filter addTextFieldWithConfigurationHandler:^(UITextField *field){field.text=self.filter;field.placeholder=T(@"Filename contains…");}];[filter addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[filter addAction:[UIAlertAction actionWithTitle:T(@"Apply") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){self.filter=filter.textFields.firstObject.text?:@"";[self renderFiles];}]];[self presentViewController:filter animated:YES completion:nil];}]];
    [tools addArrangedSubview:[self tool:@"arrow.up.arrow.down" label:T(@"Sort") action:^{UIAlertController *sort=[UIAlertController alertControllerWithTitle:T(@"Sort") message:nil preferredStyle:UIAlertControllerStyleAlert];NSArray *names=@[@"Name",@"Newest first",@"Largest first"];for(NSInteger i=0;i<names.count;i++){NSInteger index=i;[sort addAction:[UIAlertAction actionWithTitle:T(names[i]) style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){self.sortOrder=index;[self renderFiles];}]];}[sort addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:sort animated:YES completion:nil];}]];
    [tools addArrangedSubview:[self tool:self.tiles?@"list.bullet":@"square.grid.2x2" label:self.tiles?T(@"List"):T(@"Grid") action:^{self.tiles=!self.tiles;[NSUserDefaults.standardUserDefaults setBool:self.tiles forKey:@"fileGrid"];[self renderFiles];}]];
    [tools addArrangedSubview:[self tool:@"plus" label:T(@"New folder") action:^{[self editItem:nil];}]];[self.content addArrangedSubview:tools];
    NSMutableArray *entries=[NSMutableArray new];for(NSDictionary *item in self.fileEntries)if(!self.filter.length||[item[@"name"] localizedCaseInsensitiveContainsString:self.filter])[entries addObject:item];
    [entries sortUsingComparator:^NSComparisonResult(NSDictionary *a,NSDictionary *b){BOOL ad=[a[@"directory"] boolValue],bd=[b[@"directory"] boolValue];if(ad!=bd)return ad?NSOrderedAscending:NSOrderedDescending;if(self.sortOrder){NSString *key=self.sortOrder==1?@"modified":@"bytes";NSComparisonResult result=[b[key]?:@0 compare:a[key]?:@0];if(result!=NSOrderedSame)return result;}return [a[@"name"] localizedCaseInsensitiveCompare:b[@"name"]];}];
    [self.content addArrangedSubview:[self label:[NSString stringWithFormat:@"%lu %@ · %lu %@",(unsigned long)entries.count,T(@"items"),(unsigned long)self.selection.count,T(@"selected")] size:12]];
    if(self.selection.count){UIStackView *actions=[UIStackView new];actions.axis=UILayoutConstraintAxisHorizontal;actions.distribution=UIStackViewDistributionFillEqually;actions.spacing=4;
        [actions addArrangedSubview:[self button:T(@"Copy") action:^{[self chooseDestination:NO];}]];
        if(!self.peer.length)[actions addArrangedSubview:[self button:T(@"Move") action:^{[self chooseDestination:YES];}]];
        [actions addArrangedSubview:[self button:T(@"Delete") action:^{[self deleteSelection];}]];
        [actions addArrangedSubview:[self button:@"×" action:^{[self.selection removeAllObjects];[self renderFiles];}]];[self.content addArrangedSubview:actions];}
    UIStackView *gridRow=nil;NSInteger index=0;
    // Building a row per file is what makes big folders (Downloads) slow: show them in pages.
    NSInteger page=self.tiles?120:200,limit=MAX(self.shownCount,page);self.shownCount=limit;
    for(NSDictionary *item in entries){if(index>=limit)break;NSString *name=item[@"name"];BOOL directory=[item[@"directory"] boolValue],selected=[self.selection containsObject:name];NSString *detail=directory?T(@"Folder"):[NSByteCountFormatter stringFromByteCount:[item[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile];
        UIButton *file=[self card:[NSString stringWithFormat:@"%@%@",selected?@"✓  ":@"",name] detail:detail symbol:[self itemSymbol:item] action:^{if(self.selection.count){if(![self.selection containsObject:name])[self.selection addObject:name];else [self.selection removeObject:name];[self renderFiles];}else if(directory){self.path=[self itemPath:item];self.filter=@"";[self showFiles];}else [self itemMenu:item];}];
        if(selected){UIButtonConfiguration *cfg=file.configuration;cfg.background.backgroundColor=[Accent() colorWithAlphaComponent:.15];file.configuration=cfg;}
        if(self.tiles){if(index%2==0){gridRow=[UIStackView new];gridRow.axis=UILayoutConstraintAxisHorizontal;gridRow.spacing=10;gridRow.distribution=UIStackViewDistributionFillEqually;[self.content addArrangedSubview:gridRow];}UIButtonConfiguration *cfg=file.configuration;cfg.imagePlacement=NSDirectionalRectEdgeTop;cfg.imagePadding=12;cfg.preferredSymbolConfigurationForImage=[UIImageSymbolConfiguration configurationWithPointSize:48];file.configuration=cfg;[file.heightAnchor constraintGreaterThanOrEqualToConstant:158].active=YES;[gridRow addArrangedSubview:file];}
        else {UIStackView *row=[UIStackView new];row.axis=UILayoutConstraintAxisHorizontal;row.spacing=4;[row addArrangedSubview:file];UIButton *more=[self button:@"" action:^{[self itemMenu:item];}];[more setImage:[UIImage systemImageNamed:@"ellipsis"] forState:UIControlStateNormal];[more.widthAnchor constraintEqualToConstant:44].active=YES;[row addArrangedSubview:more];[self.content addArrangedSubview:row];}
#if !TARGET_OS_TV
        file.showsMenuAsPrimaryAction=NO;file.menu=[UIMenu menuWithChildren:@[[UIAction actionWithTitle:T(@"Actions") image:[UIImage systemImageNamed:@"ellipsis.circle"] identifier:nil handler:^(UIAction *action){[self itemMenu:item];}]]];
#endif
        index++;
    }
    if(self.tiles&&index%2)[gridRow addArrangedSubview:[UIView new]];
    if((NSInteger)entries.count>limit){NSInteger rest=entries.count-limit;
        [self add:[NSString stringWithFormat:T(@"Show more (%ld remaining)"),(long)rest] action:^{self.shownCount=limit+page;[self renderFiles];}];}
    if(!entries.count)[self.content addArrangedSubview:[self label:T(self.filter.length?@"No matching files.":@"This folder is empty.") size:17]];
}
#endif
- (void)editItem:(NSDictionary *)item {
    if([self.path isEqual:@"/"]){[self showError:T(@"Choose a storage folder first.")];return;}
    NSString *peer=self.peer,*path=item?[self itemPath:item]:self.path;UIAlertController *form=[UIAlertController alertControllerWithTitle:T(item?@"Rename":@"New folder") message:path preferredStyle:UIAlertControllerStyleAlert];
    [form addTextFieldWithConfigurationHandler:^(UITextField *field){field.text=item[@"name"]?:@"";field.autocorrectionType=UITextAutocorrectionTypeNo;}];
    [form addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    [form addAction:[UIAlertAction actionWithTitle:T(@"Apply") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self call:@"mutate_item" args:@[peer,path,item?@"rename":@"mkdir",form.textFields.firstObject.text?:@""] then:^(NSString *json){[self.selection removeAllObjects];[self showFiles];}];}]];[self presentViewController:form animated:YES completion:nil];
}
- (void)itemMenu:(NSDictionary *)item {
    NSString *path=[self itemPath:item];UIAlertController *menu=[UIAlertController alertControllerWithTitle:item[@"name"] message:path preferredStyle:UIAlertControllerStyleActionSheet];
    if([item[@"directory"] boolValue])[menu addAction:[UIAlertAction actionWithTitle:T(@"Open") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){self.path=path;[self.selection removeAllObjects];[self showFiles];}]];
#if !TARGET_OS_TV
    else if(!self.peer.length)[menu addAction:[UIAlertAction actionWithTitle:T(@"Open") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self call:@"local_file" args:@[path] then:^(NSString *actual){self.document=[UIDocumentInteractionController interactionControllerWithURL:[NSURL fileURLWithPath:actual]];self.document.delegate=self;if(![self.document presentPreviewAnimated:YES])[self.document presentOptionsMenuFromRect:self.view.bounds inView:self.view animated:YES];}];}]];
#endif
    [menu addAction:[UIAlertAction actionWithTitle:T(@"Select") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self.selection addObject:item[@"name"]];[self renderFiles];}]];
    [menu addAction:[UIAlertAction actionWithTitle:T(@"Copy") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self.selection removeAllObjects];[self.selection addObject:item[@"name"]];[self chooseDestination:NO];}]];
    if(![self.path isEqual:@"/"]){[menu addAction:[UIAlertAction actionWithTitle:T(@"Rename") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self editItem:item];}]];
        [menu addAction:[UIAlertAction actionWithTitle:T(@"Delete") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){[self.selection removeAllObjects];[self.selection addObject:item[@"name"]];[self deleteSelection];}]];}
    [menu addAction:[UIAlertAction actionWithTitle:T(@"Properties") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){NSString *size=[item[@"directory"] boolValue]?T(@"Folder size has not been calculated"):[NSByteCountFormatter stringFromByteCount:[item[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile];NSString *date=[item[@"modified"] doubleValue]>0?[NSDateFormatter localizedStringFromDate:[NSDate dateWithTimeIntervalSince1970:[item[@"modified"] doubleValue]] dateStyle:NSDateFormatterMediumStyle timeStyle:NSDateFormatterShortStyle]:@"—";UIAlertController *info=[UIAlertController alertControllerWithTitle:T(@"Properties") message:[NSString stringWithFormat:@"%@\n\n%@: %@\n%@: %@",path,T(@"Size"),size,T(@"Modified"),date] preferredStyle:UIAlertControllerStyleAlert];[info addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:info animated:YES completion:nil];}]];
    [menu addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];menu.popoverPresentationController.sourceView=self.view;menu.popoverPresentationController.sourceRect=CGRectMake(self.view.bounds.size.width/2,self.view.bounds.size.height/2,1,1);[self presentViewController:menu animated:YES completion:nil];
}
- (void)deleteSelection {
    if([self.path isEqual:@"/"])return;NSString *peer=self.peer;NSMutableArray *paths=[NSMutableArray new];for(NSString *name in self.selection)[paths addObject:[self.path stringByAppendingPathComponent:name]];
    UIAlertController *confirm=[UIAlertController alertControllerWithTitle:T(@"Delete permanently?") message:[NSString stringWithFormat:@"%@\n\n%@",[paths componentsJoinedByString:@"\n"],T(@"This does not use the Trash.")] preferredStyle:UIAlertControllerStyleAlert];
    [confirm addAction:[UIAlertAction actionWithTitle:T(@"Keep files") style:UIAlertActionStyleCancel handler:nil]];
    [confirm addAction:[UIAlertAction actionWithTitle:T(@"Delete") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){[self deletePaths:paths peer:peer index:0];}]];[self presentViewController:confirm animated:YES completion:nil];
}
- (void)deletePaths:(NSArray *)paths peer:(NSString *)peer index:(NSUInteger)index {
    if(index>=paths.count){[self.selection removeAllObjects];[self showFiles];return;}[self call:@"mutate_item" args:@[peer,paths[index],@"remove",@""] then:^(NSString *json){[self deletePaths:paths peer:peer index:index+1];}];
}
- (void)pickFolder:(NSString *)peer path:(NSString *)path chosen:(void (^)(NSString *))chosen {
    [self call:peer.length?@"browse":@"browse_local_path" args:peer.length?@[peer,path]:@[path] then:^(NSString *json){NSArray *values=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];UIAlertController *picker=[UIAlertController alertControllerWithTitle:T(@"Choose destination folder") message:path preferredStyle:UIAlertControllerStyleActionSheet];
        if(![path isEqual:@"/"]){[picker addAction:[UIAlertAction actionWithTitle:T(@"Use this folder") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){chosen(path);}]];[picker addAction:[UIAlertAction actionWithTitle:@"↑ .." style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self pickFolder:peer path:path.stringByDeletingLastPathComponent chosen:chosen];}]];}
        for(NSDictionary *item in values)if([item[@"directory"] boolValue])[picker addAction:[UIAlertAction actionWithTitle:[@"▸ " stringByAppendingString:item[@"name"]] style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self pickFolder:peer path:[path stringByAppendingPathComponent:item[@"name"]] chosen:chosen];}]];
        [picker addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];picker.popoverPresentationController.sourceView=self.view;picker.popoverPresentationController.sourceRect=CGRectMake(self.view.bounds.size.width/2,self.view.bounds.size.height/2,1,1);[self presentViewController:picker animated:YES completion:nil];}];
}
- (void)chooseDestination:(BOOL)moving {
    NSString *sourcePeer=self.peer;NSMutableArray *paths=[NSMutableArray new];for(NSString *name in self.selection)[paths addObject:[self.path stringByAppendingPathComponent:name]];
    UIAlertController *devices=[UIAlertController alertControllerWithTitle:T(@"Choose destination device") message:nil preferredStyle:UIAlertControllerStyleAlert];NSMutableArray *targets=[NSMutableArray arrayWithObject:@{@"id":@"",@"name":T(@"This device")}];if(!moving)[targets addObjectsFromArray:self.state[@"peers"]?:@[]];
    for(NSDictionary *target in targets)[devices addAction:[UIAlertAction actionWithTitle:target[@"name"] style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self pickFolder:target[@"id"] path:@"/" chosen:^(NSString *folder){UIAlertController *confirm=[UIAlertController alertControllerWithTitle:T(moving?@"Move":@"Copy") message:[NSString stringWithFormat:@"%@\n↓\n%@ · %@",[paths componentsJoinedByString:@"\n"],target[@"name"],folder] preferredStyle:UIAlertControllerStyleAlert];[confirm addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[confirm addAction:[UIAlertAction actionWithTitle:T(moving?@"Move":@"Copy") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){[self runTransfer:paths source:sourcePeer target:target[@"id"] folder:folder moving:moving];}]];[self presentViewController:confirm animated:YES completion:nil];}];}]];
    [devices addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:devices animated:YES completion:nil];
}
- (void)runTransfer:(NSArray *)paths source:(NSString *)source target:(NSString *)target folder:(NSString *)folder moving:(BOOL)moving {
#if !TARGET_OS_TV
    NSString *json=[[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:paths options:0 error:nil] encoding:NSUTF8StringEncoding];
    NSString *title=paths.count==1?T(moving?@"Moving":@"Copying"):[NSString stringWithFormat:T(moving?@"Moving %ld items":@"Copying %ld items"),(long)paths.count];
    [self startOperation:title route:[self routeFrom:[paths.firstObject stringByDeletingLastPathComponent] peer:source to:folder peer:target] call:@"transfer_items" args:@[source,json,target,folder,@(moving)] done:^(NSDictionary *value){
        [self toast:[NSString stringWithFormat:@"%@\n%@",T(moving?@"Moved":@"Copied"),[self routeFrom:[paths.firstObject stringByDeletingLastPathComponent] peer:source to:folder peer:target]]];}];
    return;
#endif
    self.operationAlert=[UIAlertController alertControllerWithTitle:T(moving?@"Move":@"Copy") message:T(@"Preparing files…") preferredStyle:UIAlertControllerStyleAlert];
    [self.operationAlert addAction:[UIAlertAction actionWithTitle:T(@"Stop") style:UIAlertActionStyleDestructive handler:^(UIAlertAction *action){dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{CoreCall(@"cancel_operation",@[],NO);});}]];
    [self presentViewController:self.operationAlert animated:YES completion:^{NSString *json=[[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:paths options:0 error:nil] encoding:NSUTF8StringEncoding];[self call:@"transfer_items" args:@[source,json,target,folder,@(moving)] then:^(NSString *value){UIAlertController *busy=self.operationAlert;self.operationAlert=nil;[self.selection removeAllObjects];[busy dismissViewControllerAnimated:YES completion:^{[self showFiles];
#if !TARGET_OS_TV
        if([self twoPanels])[self showOtherFiles];
#endif
        [self toast:[NSString stringWithFormat:@"%@\n%@",T(moving?@"Moved":@"Copied"),folder]];}];}];}];
}
// Short confirmation that an operation finished; disappears by itself.
- (void)toast:(NSString *)text {
    if(self.presentedViewController)return;
    UIAlertController *note=[UIAlertController alertControllerWithTitle:nil message:text preferredStyle:UIAlertControllerStyleAlert];
    [self presentViewController:note animated:YES completion:^{dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(1.4*NSEC_PER_SEC)),dispatch_get_main_queue(),^{if(note.presentingViewController)[note dismissViewControllerAnimated:YES completion:nil];});}];
}
