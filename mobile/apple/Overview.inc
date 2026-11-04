// Overview and Transfers for iPhone and iPad, in the grouped style of Settings.
// Included inside SooveeViewController.
#if !TARGET_OS_TV

- (void)openPlace:(NSDictionary *)place {
    self.peer=place[@"peer"]?:@"";
    if(self.peer.length&&![[self.state[@"peers"] valueForKey:@"id"] containsObject:self.peer]){[self showError:T(@"This device is no longer paired.")];self.peer=@"";return;}
    [self openFolder:place[@"path"]?:@"/"];
}
- (NSString *)placeDetail:(NSDictionary *)place {
    NSString *where=T(@"This device");NSString *peer=place[@"peer"];
    if([peer length])for(NSDictionary *device in self.state[@"peers"])if([device[@"id"] isEqual:peer])where=device[@"name"];
    return [NSString stringWithFormat:@"%@ · %@",where,[place[@"path"] stringByDeletingLastPathComponent]];
}

// A row with a trailing … menu; its last entry removes the item (red).
- (UIView *)rowWithMenu:(UIView *)row title:(NSString *)title actions:(NSArray *)actions remove:(dispatch_block_t)remove {
    UIAction *forget=[UIAction actionWithTitle:T(@"Remove location · keep files") image:[UIImage systemImageNamed:@"minus.circle"] identifier:nil handler:^(UIAction *a){remove();}];forget.attributes=UIMenuElementAttributesDestructive;
    UIButton *more=[UIButton buttonWithType:UIButtonTypeSystem];[more setImage:[UIImage systemImageNamed:@"ellipsis.circle"] forState:UIControlStateNormal];more.tintColor=Accent();
    more.menu=[UIMenu menuWithTitle:title children:[actions arrayByAddingObject:[UIMenu menuWithTitle:@"" image:nil identifier:nil options:UIMenuOptionsDisplayInline children:@[forget]]]];more.showsMenuAsPrimaryAction=YES;
    more.accessibilityLabel=[NSString stringWithFormat:T(@"More for %@"),title];[more.widthAnchor constraintEqualToConstant:44].active=YES;
    UIStackView *line=[[UIStackView alloc]initWithArrangedSubviews:@[row,more]];line.alignment=UIStackViewAlignmentCenter;return line;
}

- (void)showHome {
    [self clear:@"home"];[self screenTitle:T(@"Overview") back:nil action:nil];
    NSMutableArray *locations=[NSMutableArray new];
    for(NSDictionary *volume in self.state[@"storage"]?:@[]){NSString *name=volume[@"name"]?:@"Shared";
        double total=[volume[@"total"] doubleValue],free=[volume[@"free"] doubleValue];
        NSString *capacity=total>0?[NSString stringWithFormat:@"%@ %@ %@",[NSByteCountFormatter stringFromByteCount:(long long)free countStyle:NSByteCountFormatterCountStyleFile],T(@"free of"),[NSByteCountFormatter stringFromByteCount:(long long)total countStyle:NSByteCountFormatterCountStyleFile]]:nil;
        NSDictionary *location=[self locationNamed:name];BOOL network=[location[@"network"] boolValue];
        NSString *detail=network?[NSString stringWithFormat:@"%@ · %@",T(@"Network location"),capacity?:@""]:capacity;
        UIView *row=[self row:T(name) detail:detail symbol:[name isEqual:@"Shared"]?@"iphone":network?@"network":@"folder.fill" tint:[name isEqual:@"Shared"]?UIColor.systemBlueColor:network?UIColor.systemTealColor:UIColor.systemIndigoColor action:^{self.peer=@"";[self openFolder:[@"/" stringByAppendingString:name]];}];
        [locations addObject:location?[self rowWithMenu:row title:name actions:@[
            [UIAction actionWithTitle:T(@"Open") image:[UIImage systemImageNamed:@"folder"] identifier:nil handler:^(UIAction *a){self.peer=@"";[self openFolder:[@"/" stringByAppendingString:name]];}]] remove:^{[self removeLocation:name];}]:row];}
    for(NSDictionary *item in [self unavailableLocations]){NSString *name=item[@"name"];
        UIView *row=[self row:name detail:T(@"Not available now") symbol:@"externaldrive.badge.xmark" tint:UIColor.systemGrayColor action:^{[self unavailableLocation:name];}];
        [locations addObject:[self rowWithMenu:row title:name actions:@[] remove:^{[self removeLocation:name];}]];}
    [locations addObject:[self row:T(@"Add folder from Files…") detail:T(@"iCloud Drive, On My iPhone, Downloads, USB drives") symbol:@"folder.badge.plus" tint:UIColor.systemGreenColor action:^{[self addFolder];}]];
    [self section:T(@"Locations") rows:locations footer:T(@"iOS lets Soovee use its own folder and the folders you choose in Files. Other apps’ private data stays protected.")];

    NSMutableArray *favorites=[NSMutableArray new];
    for(NSDictionary *place in [self places:@"favorites"])[favorites addObject:[self row:place[@"name"] detail:[self placeDetail:place] symbol:@"star.fill" tint:UIColor.systemYellowColor action:^{[self openPlace:place];}]];
    if(favorites.count)[self section:T(@"Favorites") rows:favorites footer:nil];

    NSMutableArray *recent=[NSMutableArray new];
    for(NSDictionary *place in [[self places:@"recentFolders"] subarrayWithRange:NSMakeRange(0,MIN(5,[self places:@"recentFolders"].count))])
        [recent addObject:[self row:place[@"name"] detail:[self placeDetail:place] symbol:@"clock" tint:UIColor.systemGrayColor action:^{[self openPlace:place];}]];
    for(NSDictionary *place in [[self places:@"recentFiles"] subarrayWithRange:NSMakeRange(0,MIN(5,[self places:@"recentFiles"].count))]){
        NSDictionary *folder=@{@"peer":place[@"peer"]?:@"",@"path":[place[@"path"] stringByDeletingLastPathComponent]};
        [recent addObject:[self row:place[@"name"] detail:[self placeDetail:place] symbol:@"doc" tint:UIColor.systemTealColor action:^{[self openPlace:folder];}]];}
    if(recent.count)[self section:T(@"Recent") rows:recent footer:nil];

    NSMutableArray *devices=[NSMutableArray new];
    for(NSDictionary *peer in self.state[@"peers"]){NSDictionary *near=nil;for(NSDictionary *device in self.nearby.allValues)if([device[@"id"] isEqual:peer[@"id"]])near=device;
        [devices addObject:[self row:peer[@"name"] detail:T(near?@"On this network":@"Not found on this network") symbol:[self deviceSymbol:near[@"kind"]] tint:near?UIColor.systemGreenColor:UIColor.systemGrayColor action:^{[self openPaired:peer near:near];}]];}
    [devices addObject:[self row:T(@"Find a device or scan QR") detail:nil symbol:@"qrcode.viewfinder" tint:Accent() action:^{[self showNearby];}]];
    [self section:T(@"Devices") rows:devices footer:nil];

    [self section:nil rows:@[[self row:T(@"Import files…") detail:T(@"Copy files into Soovee with the system picker") symbol:@"square.and.arrow.down" tint:UIColor.systemOrangeColor action:^{
        UIDocumentPickerViewController *picker=[[UIDocumentPickerViewController alloc]initForOpeningContentTypes:@[UTTypeItem] asCopy:YES];picker.allowsMultipleSelection=YES;picker.delegate=self;[self presentViewController:picker animated:YES completion:nil];}],
        [self row:T(@"Settings") detail:nil symbol:@"gearshape" tint:UIColor.systemGrayColor action:^{[self showSettings];}]] footer:nil];
}

- (void)showTransfers {
    [self clear:@"transfers"];[self screenTitle:T(@"Transfers") back:nil action:nil];
    [self call:@"operation_snapshot" args:@[] then:^(NSString *json){if(![self.screen isEqual:@"transfers"])return;
        NSDictionary *value=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];if(![value isKindOfClass:NSDictionary.class])value=@{};
        [self renderTransfers:value];}];
}
- (void)renderTransfers:(NSDictionary *)value {
    for(UIView *view in [self.content.arrangedSubviews subarrayWithRange:NSMakeRange(1,self.content.arrangedSubviews.count-1)]){[self.content removeArrangedSubview:view];[view removeFromSuperview];}
    NSString *status=value[@"status"]?:@"";BOOL running=[status isEqual:@"running"];
    if(!value.count){[self section:T(@"Activity") rows:@[[self row:T(@"No transfers yet.") detail:T(@"Copies, moves and archives appear here.") symbol:@"tray" tint:UIColor.systemGrayColor action:nil]] footer:nil];}
    else{
        NSDictionary *names=@{@"copy":@"Copy",@"move":@"Move",@"extract":@"Extract here",@"compress":@"Compress"};
        NSDictionary *states=@{@"running":@"Running",@"done":@"Completed",@"error":@"Failed",@"canceled":@"Canceled"};
        NSDictionary *symbols=@{@"running":@"arrow.triangle.2.circlepath",@"done":@"checkmark.circle.fill",@"error":@"exclamationmark.triangle.fill",@"canceled":@"xmark.circle.fill"};
        NSDictionary *tints=@{@"running":UIColor.systemBlueColor,@"done":UIColor.systemGreenColor,@"error":UIColor.systemRedColor,@"canceled":UIColor.systemGrayColor};
        NSString *size=[NSByteCountFormatter stringFromByteCount:[value[@"bytes"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile];
        NSMutableArray *rows=[NSMutableArray arrayWithObject:[self row:T(names[value[@"action"]]?:@"Transfers") detail:T(states[status]?:status) symbol:symbols[status]?:@"arrow.left.arrow.right" tint:tints[status]?:Accent() value:[NSString stringWithFormat:@"%@/%@ · %@",value[@"completed"]?:@0,value[@"files"]?:@0,size] chevron:NO menu:nil action:nil]];
        if([value[@"current"] length])[rows addObject:[self row:T(@"Current file") detail:[value[@"current"] lastPathComponent] symbol:@"doc" tint:UIColor.systemGrayColor action:nil]];
        if([value[@"destination"] length])[rows addObject:[self row:T(@"Destination") detail:value[@"destination"] symbol:@"folder" tint:UIColor.systemGrayColor action:nil]];
        if([status isEqual:@"error"]&&[value[@"message"] length])[rows addObject:[self row:T(@"Error") detail:T(value[@"message"]) symbol:@"exclamationmark.bubble" tint:UIColor.systemRedColor action:nil]];
        [self section:T(running?@"In progress":@"Last operation") rows:rows footer:running?T(@"Keep Soovee open until it finishes. iOS pauses apps in the background."):nil];
        if(running)[self section:nil rows:@[[self row:T(@"Stop") detail:nil symbol:nil tint:UIColor.systemRedColor value:nil chevron:NO menu:nil action:^{dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{CoreCall(@"cancel_operation",@[],NO);});}]] footer:T(@"Files already finished stay at the destination.")];
    }
    [self section:T(@"Support") rows:@[[self row:T(@"Diagnostic log") detail:T(@"Errors and events, for troubleshooting") symbol:@"doc.text.magnifyingglass" tint:UIColor.systemGrayColor action:^{[self showLog];}]] footer:nil];
    if(running)dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(NSEC_PER_SEC/2)),dispatch_get_main_queue(),^{if([self.screen isEqual:@"transfers"])[self call:@"operation_snapshot" args:@[] then:^(NSString *json){if(![self.screen isEqual:@"transfers"])return;NSDictionary *next=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];[self renderTransfers:[next isKindOfClass:NSDictionary.class]?next:@{}];}];});
}
#endif
